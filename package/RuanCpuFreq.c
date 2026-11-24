// SPDX-License-Identifier: BSD-2-Clause-Patent
// ruan-cpufreq=<n>: CPU frequency vote for ruan's EPSS domains (SM7435, live DT qcom,cpufreq-hw-epss: freq-domain0 17d91000 =
// cpus 0-3 A55, freq-domain1 17d92000 = cpus 4-7 A78). Layout of qcom-cpufreq-hw's "epss" data, as UniXNU-Dizi-Ruan's
// CpuFreqProbe.cpp: domain_state 0x20, dcvs_ctrl 0xb0, LUT 0x100 (4-byte rows: 31:30 source, 18:16 cores, 7:0 L value x 19.2 MHz),
// perf_state 0x320 (+4*i per core when dcvs_ctrl bit 0 is set). The DT has qcom,skip-enable-check, so reg 0x0 is not checked.
//   1  report each domain's current level and LUT top (printf, so it reaches the boot page)
//   2  also vote the highest non-turbo level in both domains, once each domain's state reads non-zero (cluster up)
//   3  mode 2, then a governor (below) for both domains and the L3
// Mode 3: the L3 is the live DT's qcom,dcvs/l3 (qcom,dcvs-hw type 2, the vendor name for upstream's qcom,epss-l3):
// l3-base 17d90000, l3tbl-base 17d90100 (40 rows, the same row format), slow path "sp" qcom,shared-offset 0x90 = the vote register.
// Every 16 ms a domain's load is its busiest CPU's busy share (1 - recount idle time over the window); it gets the lowest level
// at or above 1.25 x load x its current clock (schedutil's margin), the top at 90 % busy; up at once, down after 4 windows asking
// for less. A touch report (ruan_touch_events moves) holds both domains at the top for ruan-cpufreq-boost-ms (default 1000, 0 off).
// The L3 follows the faster domain: the lowest L3 level at or above the same fraction of its top. XNU cpu numbers follow the DT.
// Mode 3 thermal cap: the big-core sensors (live DT zones cpu-1-0..7 = tsens0 TM 0xc263000 sensors 3..10; TM_Sn_STATUS 0xa0 + 4n,
// bits 11:0 signed deci-C, bit 21 valid, as tsens-v2.c). Over 90 C domain 1 is held at or below its middle level (at once, also
// during a touch boost) until the hottest of them is back under 85 C. No valid reading = no cap (the EPSS dcvsh clamp still applies).
// ruan_cpufreq_temp_dc is the last hottest reading, ruan_cpufreq_capped counts windows spent capped.
// Screen off (RuanInput.c ruan_screen_off, the backlight at 0): both domains at most their second-lowest level, no touch boost;
// asleep (ruan-sleep=1, ruan_sleeping) the lowest. The L3 follows them down. Load is recount's per-CPU idle time, which already
// counts the idle thread's spin (noidle WFI-less idle) as idle: processor_idle marks the CPU idle before its loop.
#include <stdint.h>
#ifndef RUAN_CPUFREQ_HOST
#include <kern/thread.h>
#include <kern/misc_protos.h>
#include <kern/processor.h>
#include <kern/recount.h>
#include <machine/machine_routines.h>
#include <mach/mach_time.h>
#include <pexpert/pexpert.h>
extern wait_result_t assert_wait_timeout(event_t, wait_interrupt_t, uint32_t, uint32_t);
#endif

enum {kRows = 40, kState = 0x20, kDcvs = 0xb0, kLut = 0x100, kPerf = 0x320, kL3Vote = 0x90};

// Highest non-turbo row of a LUT (*mhz its clock), as qcom_cpufreq_hw_read_lut: the table ends where a frequency repeats, a row
// with core count 1 past the first is a turbo row. -1 for an empty table.
int ruan_cpufreq_pick(const uint32_t *lut, unsigned rows, unsigned *mhz)
{
	int best = -1;
	unsigned prev = 0;
	for (unsigned i = 0; i < rows; i++) {
		uint32_t d = lut[i];
		unsigned f = (d >> 30) ? (d & 0xff) * 192 / 10 : 300;
		if (!(d & 0xff) || (i && f == prev)) {
			break;
		}
		prev = f;
		if (i && ((d >> 16) & 7) == 1) {
			continue;
		}
		best = (int)i;
		*mhz = f;
	}
	return best;
}

// Mode 3: a LUT's levels in ascending clock (row index, MHz), turbo rows left out when skip_turbo (the L3's core count field
// means nothing). Same end rule as ruan_cpufreq_pick. Returns the count.
unsigned ruan_cpufreq_levels(const uint32_t *lut, unsigned rows, int skip_turbo, uint8_t *row, uint16_t *mhz)
{
	unsigned n = 0, prev = 0;
	for (unsigned i = 0; i < rows; i++) {
		uint32_t d = lut[i];
		unsigned f = (d >> 30) ? (d & 0xff) * 192 / 10 : 300;
		if (!(d & 0xff) || (i && f == prev)) {
			break;
		}
		prev = f;
		if (skip_turbo && i && ((d >> 16) & 7) == 1) {
			continue;
		}
		unsigned at = n++;
		while (at && mhz[at - 1] > f) {
			mhz[at] = mhz[at - 1], row[at] = row[at - 1], at--;
		}
		mhz[at] = (uint16_t)f, row[at] = (uint8_t)i;
	}
	return n;
}

// A tsens-v2 TM_Sn_STATUS word in deci-C, INT32_MIN when the valid bit (21) is clear.
int32_t ruan_tsens_dc(uint32_t v)
{
	return (v & (1u << 21)) ? (int32_t)(v << 20) >> 20 : INT32_MIN;
}

// Mode 3: the level a domain wants for a window, from its current level and its busiest CPU's busy share (per mille).
unsigned ruan_cpufreq_want(const uint16_t *mhz, unsigned n, unsigned cur, unsigned busy_pm)
{
	if (busy_pm >= 900) {
		return n - 1;
	}
	uint32_t need = (uint32_t)mhz[cur] * busy_pm * 5 / 4000;
	unsigned w = 0;
	while (w + 1 < n && mhz[w] < need) {
		w++;
	}
	return w;
}

#if defined(RUAN_CPUFREQ_HOST) && defined(RUAN_CPUFREQ_SELFTEST)
// cc -DRUAN_CPUFREQ_HOST -DRUAN_CPUFREQ_SELFTEST RuanCpuFreq.c && ./a.out
#include <assert.h>
int main(void)
{
	// source 0 row (300), 691, 1094, 1958, a turbo row 2400 (cores 1), then a repeat
	uint32_t lut[] = {0x00000001, 0x40030024, 0x40030039, 0x40030066, 0x4001007d, 0x4001007d};
	uint8_t row[8];
	uint16_t mhz[8];
	unsigned n = ruan_cpufreq_levels(lut, 6, 1, row, mhz);
	assert(n == 4 && mhz[0] == 300 && mhz[3] == 1958 && row[3] == 3);
	assert(ruan_cpufreq_levels(lut, 6, 0, row, mhz) == 5 && row[4] == 4);
	n = ruan_cpufreq_levels(lut, 6, 1, row, mhz);
	assert(ruan_cpufreq_want(mhz, n, 3, 950) == 3);         // hispeed jump
	assert(ruan_cpufreq_want(mhz, n, 3, 0) == 0);           // idle: the bottom
	assert(ruan_cpufreq_want(mhz, n, 3, 400) == 2);         // 1958 x 0.4 x 1.25 = 979 -> 1094
	assert(ruan_cpufreq_want(mhz, n, 0, 800) == 0);         // 300 x 0.8 x 1.25 = 300 -> 300
	assert(ruan_tsens_dc((1u << 21) | 0x384) == 900 && ruan_tsens_dc((1u << 21) | 0xff6) == -10 && ruan_tsens_dc(0x384) == INT32_MIN);
	return 0;
}
#endif

#ifndef RUAN_CPUFREQ_HOST
static unsigned mode;
static volatile uint32_t *dom[2];       // the domain windows, for mode 3
extern volatile uint32_t ruan_touch_events;     // RuanInput.c: one per touch report
extern volatile uint32_t ruan_screen_off, ruan_sleeping;        // RuanInput.c: backlight at 0, ruan-sleep=1 with it
static volatile uint32_t busy_last[2], boosting;        // mode 3: last window's busiest CPU per domain (per mille), touch boost on
volatile int32_t ruan_cpufreq_temp_dc = INT32_MIN;      // mode 3: hottest big-core tsens reading, deci-C
volatile uint32_t ruan_cpufreq_capped;                  // mode 3: windows with domain 1 thermally capped

static void
vote(volatile uint32_t *r, uint32_t row)
{
	unsigned cores = (r[kDcvs / 4] & 1) ? 4 : 1;   // ruan: 4 CPUs per domain
	for (unsigned i = 0; i < cores; i++) {
		r[(kPerf + 4 * i) / 4] = row;
	}
}

static void
domain(unsigned d, uint64_t phys)
{
	volatile uint32_t *r = (volatile uint32_t *)ml_io_map(phys, 0x1000);
	uint32_t lut[kRows];
	unsigned waited = 0, mhz = 0;
	if (!r) {
		printf("ruan-cpufreq: d%u map failed\n", d);
		return;
	}
	while (!(r[kState / 4] & 0xff) && waited++ < 300) {   // a cluster whose cores are all off reads 0
		assert_wait_timeout((event_t)&mode, THREAD_UNINT, 100, NSEC_PER_MSEC);
		thread_block(THREAD_CONTINUE_NULL);
	}
	for (unsigned i = 0; i < kRows; i++) {
		lut[i] = r[(kLut + 4 * i) / 4];
	}
	int top = ruan_cpufreq_pick(lut, kRows, &mhz);
	printf("ruan-cpufreq: d%u state %u MHz, top row %d = %u MHz, dcvs 0x%x\n", d, (r[kState / 4] & 0xff) * 192 / 10, top, mhz,
	    r[kDcvs / 4]);
	if (mode < 2 || top < 0) {
		return;
	}
	vote(r, (uint32_t)top);
	dom[d] = r;
	assert_wait_timeout((event_t)&mode, THREAD_UNINT, 200, NSEC_PER_MSEC);
	thread_block(THREAD_CONTINUE_NULL);
	printf("ruan-cpufreq: d%u voted row %d, state now %u MHz\n", d, top, (r[kState / 4] & 0xff) * 192 / 10);
}

// Mode 3 (see the header). Level sets 0, 1 = the domains, 2 = the L3.
static void
governor(void)
{
	static uint8_t row[3][kRows];
	static uint16_t mhz[3][kRows];
	volatile uint32_t *win[3] = {dom[0], dom[1], (volatile uint32_t *)ml_io_map(0x17d90000, 0x1000)};
	processor_t cpu[8];
	unsigned n[3] = {0}, cur[3] = {0}, down[3] = {0}, boost_ms = 1000, lim[3] = {~0u, ~0u, ~0u};
	volatile uint32_t *tm = (volatile uint32_t *)ml_io_map(0x0c263000, 0x1000);   // tsens0 TM (live DT thermal-sensor@c263000)
	uint64_t idle[8] = {0}, last = 0, boost_abs = 0, boost_end = 0;
	uint32_t lut[kRows], touches = ruan_touch_events;

	PE_parse_boot_argn("ruan-cpufreq-boost-ms", &boost_ms, sizeof(boost_ms));
	nanoseconds_to_absolutetime((uint64_t)boost_ms * NSEC_PER_MSEC, &boost_abs);
	for (unsigned d = 0; d < 3; d++) {
		if (!win[d]) {
			continue;
		}
		for (unsigned i = 0; i < kRows; i++) {
			lut[i] = win[d][(kLut + 4 * i) / 4];
		}
		n[d] = ruan_cpufreq_levels(lut, kRows, d < 2, row[d], mhz[d]);
		cur[d] = n[d] ? n[d] - 1 : 0;   // mode 2 left the domains at the top; the L3 starts there too
	}
	if (n[2]) {
		win[2][kL3Vote / 4] = row[2][cur[2]];
	}
	printf("ruan-cpufreq: governor d0 %u levels, d1 %u, l3 %u (top %u MHz)\n", n[0], n[1], n[2], n[2] ? mhz[2][n[2] - 1] : 0);
	for (int c = 0; c < 8; c++) {
		cpu[c] = cpu_to_processor(c);
	}
	for (;;) {
		uint64_t t = mach_absolute_time(), dt = t - last;
		unsigned busy[2] = {0, 0}, frac = 0;

		for (int c = 0; c < 8; c++) {
			struct recount_usage usage = {};
			uint64_t now_idle = 0;
			if (cpu[c] == PROCESSOR_NULL) {
				continue;       // a CPU XNU never started counts as idle, not as busy
			}
			recount_processor_usage(&cpu[c]->pr_recount, &usage, &now_idle);
			uint64_t di = now_idle - idle[c];
			idle[c] = now_idle;
			unsigned b = (!last || di >= dt) ? 0 : (unsigned)((dt - di) * 1000 / dt);
			if (b > busy[c / 4]) {
				busy[c / 4] = b;
			}
		}
		int32_t dc = INT32_MIN;
		for (unsigned s = 3; tm && s <= 10; s++) {
			int32_t v = INT32_MIN;
			for (unsigned i = 0; i < 3 && v == INT32_MIN; i++) {     // tsens.c: up to three reads for the valid bit
				v = ruan_tsens_dc(tm[(0xa0 + 4 * s) / 4]);
			}
			dc = v > dc ? v : dc;
		}
		ruan_cpufreq_temp_dc = dc;
		if (n[1]) {
			unsigned capped = lim[1] < n[1] - 1;
			if (dc > 900 || (capped && dc > 850)) {
				lim[1] = (n[1] - 1) / 2;
				ruan_cpufreq_capped++;
			} else {
				lim[1] = ~0u;
			}
			if (capped != (lim[1] < n[1] - 1)) {
				printf("ruan-cpufreq: d1 thermal cap %s at %d dC\n", capped ? "off" : "on", dc);
			}
		}
		const unsigned off_cap = ruan_sleeping ? 0 : ruan_screen_off ? 1 : ~0u;   // level index cap while the screen is off
		busy_last[0] = busy[0], busy_last[1] = busy[1];
		if (last && boost_abs && ruan_touch_events != touches && !ruan_screen_off) {
			touches = ruan_touch_events;
			boost_end = t + boost_abs;
		}
		for (unsigned d = 0; d < 3; d++) {
			if (!n[d] || !win[d]) {
				continue;
			}
			unsigned want, l = lim[d];
			if (d < 2) {
				want = t < boost_end && !ruan_screen_off ? n[d] - 1 : ruan_cpufreq_want(mhz[d], n[d], cur[d], busy[d]);
				l = l < off_cap ? l : off_cap;
			} else {
				for (want = 0; want + 1 < n[2] && (uint32_t)mhz[2][want] * 1000 < (uint32_t)mhz[2][n[2] - 1] * frac; want++) {
				}
			}
			want = want < l ? want : l;
			if (want > cur[d] || (want < cur[d] && (cur[d] > l || ++down[d] >= 4))) {
				cur[d] = want;
				down[d] = 0;
				if (d < 2) {
					vote(win[d], row[d][want]);
				} else {
					win[2][kL3Vote / 4] = row[2][want];
				}
			} else if (want >= cur[d]) {
				down[d] = 0;
			}
			if (d < 2) {
				unsigned f = (uint32_t)mhz[d][cur[d]] * 1000 / mhz[d][n[d] - 1];
				frac = f > frac ? f : frac;
			}
		}
		boosting = t < boost_end && !ruan_screen_off;
		last = t;
		assert_wait_timeout((event_t)&mode, THREAD_UNINT, 16, NSEC_PER_MSEC);
		thread_block(THREAD_CONTINUE_NULL);
	}
}

static void
run(void *arg __unused, wait_result_t wr __unused)
{
	domain(0, 0x17d91000);
	domain(1, 0x17d92000);
	if (mode >= 3) {
		governor();
	}
}

volatile uint32_t ruan_cpufreq_started;   // 1 once the thread runs; USB `cpufreq` reads it

// USB `cpufreq` (UsbDebugCdc.cpp): mode, start state, both domains' live state/vote, hottest big core, capped windows, then the
// last window's busiest CPU per domain (per mille), touch boost, screen off and asleep (RuanInput.c).
void
ruan_cpufreq_report(char *out, unsigned len)
{
	unsigned s0 = dom[0] ? (dom[0][kState / 4] & 0xff) * 192 / 10 : 0, s1 = dom[1] ? (dom[1][kState / 4] & 0xff) * 192 / 10 : 0;
	snprintf(out, len, "mode %u started %u d0 %u MHz d1 %u MHz temp %d dC capped %u busy %u/%u boost %u screen-off %u sleep %u", mode,
	    ruan_cpufreq_started, s0, s1, ruan_cpufreq_temp_dc, ruan_cpufreq_capped, busy_last[0], busy_last[1], boosting, ruan_screen_off,
	    ruan_sleeping);
}

void
ruan_cpufreq_start(void)
{
	thread_t thread;
	if (ruan_cpufreq_started) {
		return;
	}
	if (!PE_parse_boot_argn("ruan-cpufreq", &mode, sizeof(mode)) || !mode) {
		return;
	}
	ruan_cpufreq_started = 1;
	if (kernel_thread_start(run, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}
#endif

// SPDX-License-Identifier: BSD-2-Clause-Patent
// ruan-cpufreq=<n>: CPU frequency vote for ruan's EPSS domains (SM7435, live DT qcom,cpufreq-hw-epss: freq-domain0 17d91000 =
// cpus 0-3 A55, freq-domain1 17d92000 = cpus 4-7 A78). Layout of qcom-cpufreq-hw's "epss" data, as UniXNU-Dizi-Ruan's
// CpuFreqProbe.cpp: domain_state 0x20, dcvs_ctrl 0xb0, LUT 0x100 (4-byte rows: 31:30 source, 18:16 cores, 7:0 L value x 19.2 MHz),
// perf_state 0x320 (+4*i per core when dcvs_ctrl bit 0 is set). The DT has qcom,skip-enable-check, so reg 0x0 is not checked.
//   1  report each domain's current level and LUT top (printf, so it reaches the boot page)
//   2  also vote the highest non-turbo level in both domains, once each domain's state reads non-zero (cluster up)
// No governor: a fixed vote. shortcut: no thermal handling beyond the firmware's own limits; port Dizi-Ruan's mode 4 for that.
#include <stdint.h>
#ifndef RUAN_CPUFREQ_HOST
#include <kern/thread.h>
#include <kern/misc_protos.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
extern wait_result_t assert_wait_timeout(event_t, wait_interrupt_t, uint32_t, uint32_t);
#endif

enum {kRows = 40, kState = 0x20, kDcvs = 0xb0, kLut = 0x100, kPerf = 0x320};

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

#ifndef RUAN_CPUFREQ_HOST
static unsigned mode;

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
	unsigned cores = (r[kDcvs / 4] & 1) ? 4 : 1;   // ruan: 4 CPUs per domain
	for (unsigned i = 0; i < cores; i++) {
		r[(kPerf + 4 * i) / 4] = (uint32_t)top;
	}
	assert_wait_timeout((event_t)&mode, THREAD_UNINT, 200, NSEC_PER_MSEC);
	thread_block(THREAD_CONTINUE_NULL);
	printf("ruan-cpufreq: d%u voted row %d, state now %u MHz\n", d, top, (r[kState / 4] & 0xff) * 192 / 10);
}

static void
run(void *arg __unused, wait_result_t wr __unused)
{
	domain(0, 0x17d91000);
	domain(1, 0x17d92000);
}

void
ruan_cpufreq_start(void)
{
	thread_t thread;
	if (!PE_parse_boot_argn("ruan-cpufreq", &mode, sizeof(mode)) || !mode) {
		return;
	}
	if (kernel_thread_start(run, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}
#endif

/* ruan boot-progress page: the hooks of the OS profile's zzz-boot-progress.patch, drawn straight into the UEFI GOP
 * framebuffer that video_console maps (boot_progress_bind). patches/xnu/ruan-boot-progress.patch links these always;
 * without the boot-arg boot-progress=<nonzero> every hook returns at once and the console works as before.
 *
 * Layout (portrait 1600x2560 at 2x: 100 x 80 cells of 16x32 px):
 *   title    t= seconds since kernel entry, idle= seconds since the last event, irq/procs/exec/exit counters,
 *            mem= max_mem in MiB (+ the MiB adopted from outside the window, ruan-memory-outside.patch)
 *   boxes    11 milestones; grey = not reached, green = reached, yellow = the latest reached, red = failed
 *   now      the last kernel stage string
 *   events   kernel stages, userland milestones and launchd's "L " lines about backboardd, bootstrap/on-demand mode and
 *            boot tasks (mirror_line; wrap-around, '>' marks the newest line)
 *   procs    every exec'd pid with its final name; green running, grey exited 0, red exited non-zero, yellow refused
 *   console  printf/kprintf lines (wrap-around, '>' row = the line being written)
 * Smaller (fuxi-style) version of UniXNU-Dizi-Ruan package/BootProgress.c, written against xnu-10063 hooks. */
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <kern/boot_progress.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

extern int snprintf(char *, size_t, const char *, ...) __printflike(3, 4);
extern unsigned char iso_font[256 * 16];
extern int nprocs;
/* Memory the kernel ended up with (arm_vm_init.c, patches/xnu/ruan-memory-outside.patch machine_routines.c). */
extern uint64_t max_mem;
extern unsigned long gPhysBase, real_phys_size;
extern uint64_t arm_vm_outside_base, arm_vm_outside_end;
extern uint32_t ml_outside_memory_pages, ml_outside_memory_refused;
extern wait_result_t assert_wait_timeout(event_t, wait_interrupt_t, uint32_t, uint32_t);
extern wait_result_t thread_block(thread_continue_t);

#define S 2                     /* glyph scale */
#define CW (8 * S)
#define CH (16 * S)
#define MAXCOLS 128
#define RING 48
#define PROCS 128

enum { M_KERNEL, M_VM, M_SCREEN, M_SCHED, M_IOKIT, M_BSD, M_ROOT, M_LAUNCHD, M_DAEMONS, M_BACKBOARDD, M_SPRINGBOARD, M_COUNT };
static const char *const m_name[M_COUNT] = {"KERNEL", "VM", "SCREEN", "SCHED", "IOKIT", "BSD", "ROOTFS", "LAUNCHD",
	                                    "DAEMONS", "BACKBOARD", "SPRINGBRD"};
/* kernel stage strings that mark a milestone (startup.c, arm_init.c, bsd_init.c) */
static const char *const m_stage[M_COUNT] = {NULL, "arm_vm_init returned", NULL, "sched_startup", "PE_init_iokit",
	                                     "bsd_init enter", "vfs_mountroot mounted; authentication pending"};

enum { P_RUN, P_EXIT0, P_FAIL, P_REFUSED };
static const uint32_t p_color[] = {0x40e060, 0x808080, 0xff4040, 0xffd000};

static int enabled;
static char tag[24];
static uint64_t freq;
static volatile uint32_t *fb;
static unsigned fb_w, fb_h, fb_stride, cols, rows;
static unsigned r_box, r_now, r_events, n_events, r_procs, n_procrows, r_log, n_log;
static volatile int draw_lock, dirty, yield_wanted;
/* yielded: the display driver owns the panel (boot_progress_prepare_scanout). ban_painting: the banner is drawing. After the
 * hand-off every pixel store but the banner's is dropped, so a full redraw already running when the panel was handed over
 * cannot leave the page over the OS's frame (rb8s: the page stood over the Apple logo, 2026-11-14). */
static volatile int yielded, ban_painting;

static uint64_t m_ms[M_COUNT];
static uint8_t m_state[M_COUNT];        /* 0 pending, 1 reached, 2 failed */
static unsigned m_count[M_COUNT], m_last;
static char now[MAXCOLS];
/* Sticky rows under "now": 0 the ram-data result, 1 the last APFS mount-by-role console line, 2 what is mounted on
 * /private/var once launchd runs (package/RamRootProbe.c ram_data_describe). Events scroll; these do not. */
#define PINS 3
static char pin[PINS][MAXCOLS];
static uint64_t last_event_ms;
static uint64_t irqs;
static unsigned execs, exits;

static char ev[RING][MAXCOLS];
static unsigned ev_n;
static char lg[RING][MAXCOLS];
static unsigned lg_n, cur_len;
static char cur[MAXCOLS];
static struct { int pid; uint8_t state; char name[24]; } pr[PROCS];
static unsigned pr_n;

/* ---- ruan-ramoops=1: the log in the stock ramoops console zone (PROPOSALS.md P1) ----
 * The console text and every event line also go to the console zone of ruan's stock ramoops region (reserved-memory
 * ramoops@80D00000: two 256 KiB dmesg records, then the 512 KiB console zone), in Linux's persistent_ram_buffer format
 * (refs/UniXNU-j716f package/BootRamoops.c): "DBGC", the write position, the used size, then the ring. After a warm
 * reset DarwinBoot's "upload" (fastboot get_staged) or Android's /sys/fs/pstore/console-ramoops-0 gives it back;
 * scripts/read-ramoops.py parses it. Before boot_progress_start maps the zone, text waits in an 8 KiB buffer.
 * Off without the boot-arg (the zone then keeps Android's last log). */
#define ZONE_BASE  0x80D80000UL
#define ZONE_SIZE  0x80000UL
#define ZONE_SIG   0x43474244U          /* "DBGC" */
#define ZONE_HEAD  12U
#define ZONE_DATA  (ZONE_SIZE - ZONE_HEAD)
extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
static unsigned ramoops;
static volatile uint8_t *zone;
static char zone_early[8192];
static unsigned zone_early_len;
static volatile int zone_lock;
static volatile uint64_t held_ms;     /* ms() of the first boot-progress hold, for ruan-autoreset */

/* interrupts masked while held, so the holder is never preempted on one CPU (j716f take/give) */
static void
zone_put(const char *text, unsigned n)
{
	uint64_t daif;
	if (!ramoops) {
		return;
	}
	__asm__ volatile ("mrs %0, daif\n\tmsr daifset, #3" : "=r"(daif) :: "memory");
	while (__atomic_exchange_n(&zone_lock, 1, __ATOMIC_ACQUIRE)) {
	}
	if (!zone) {
		for (unsigned i = 0; i < n && zone_early_len < sizeof(zone_early); i++) {
			zone_early[zone_early_len++] = text[i];
		}
	} else {
		volatile uint32_t *head = (volatile uint32_t *)zone;
		uint32_t start = head[1], size = head[2];
		for (unsigned i = 0; i < n; i++) {
			zone[ZONE_HEAD + start] = (uint8_t)text[i];
			start = start + 1 == ZONE_DATA ? 0 : start + 1;
		}
		head[1] = start;
		head[2] = size + n > ZONE_DATA ? ZONE_DATA : size + n;
		__asm__ volatile ("dsb sy" ::: "memory");
	}
	__atomic_store_n(&zone_lock, 0, __ATOMIC_RELEASE);
	__asm__ volatile ("msr daif, %0" :: "r"(daif) : "memory");
}

/* from boot_progress_start (the VM is up): map the zone, start it empty, then the early text */
static void
zone_map(void)
{
	if (!ramoops || zone) {
		return;
	}
	volatile uint8_t *z = (volatile uint8_t *)ml_io_map(ZONE_BASE, ZONE_SIZE);
	if (!z) {
		return;
	}
	volatile uint32_t *head = (volatile uint32_t *)z;
	head[1] = 0;
	head[2] = 0;
	head[0] = ZONE_SIG;
	zone = z;
	zone_put(zone_early, zone_early_len);
}

static uint64_t
ms(void)
{
	if (!freq) {
		freq = __builtin_arm_rsr64("CNTFRQ_EL0");
	}
	return freq ? __builtin_arm_rsr64("CNTVCT_EL0") / (freq / 1000) : 0;
}

/* ---- drawing: 32-bit stores only, the mapping is device memory (no memset/dc zva) ---- */

static void
fill(unsigned x, unsigned y, unsigned w, unsigned h, uint32_t c)
{
	if (x >= fb_w || y >= fb_h || (yielded && !ban_painting)) {
		return;
	}
	w = x + w > fb_w ? fb_w - x : w;
	h = y + h > fb_h ? fb_h - y : h;
	for (unsigned j = 0; j < h; j++) {
		volatile uint32_t *p = fb + (y + j) * fb_stride + x;
		for (unsigned i = 0; i < w; i++) {
			p[i] = c;
		}
	}
}

static void
glyph(unsigned x, unsigned y, unsigned char ch, uint32_t fg, uint32_t bg)
{
	if (x + CW > fb_w || y + CH > fb_h || (yielded && !ban_painting)) {
		return;
	}
	for (unsigned line = 0; line < 16 * S; line++) {
		unsigned char bits = iso_font[ch * 16 + line / S];
		volatile uint32_t *p = fb + (y + line) * fb_stride + x;
		for (unsigned i = 0; i < CW; i++) {
			p[i] = (bits >> (i / S)) & 1 ? fg : bg;
		}
	}
}

/* text at a cell position, padded with bg to width cells */
static void
text_at(unsigned px, unsigned py, const char *s, unsigned width, uint32_t fg, uint32_t bg)
{
	for (unsigned i = 0; i < width; i++) {
		unsigned char c = *s ? (unsigned char)*s++ : ' ';
		glyph(px + i * CW, py, c, fg, bg);
	}
}

static void
row_text(unsigned row, const char *s, uint32_t fg, uint32_t bg)
{
	if (row < rows) {
		text_at(0, row * CH, s, cols, fg, bg);
	}
}

static void
draw_title(void)
{
	char line[MAXCOLS];
	uint64_t t = ms();
	snprintf(line, sizeof(line), "%s%s%sruan bp t=%llu.%llus idle=%llus irq=%llu procs=%d exec=%u exit=%u mem=%lluM+%lluM",
	    tag[0] ? "[" : "", tag, tag[0] ? "] " : "", t / 1000, t / 100 % 10, (t - last_event_ms) / 1000, irqs, nprocs, execs,
	    exits, max_mem >> 20, ((uint64_t)ml_outside_memory_pages * PAGE_SIZE) >> 20);
	row_text(0, line, 0x000000, 0xc0c0c0);
}

static void
draw_boxes(void)
{
	unsigned per_row = (M_COUNT + 1) / 2, bw = fb_w / per_row;
	for (unsigned m = 0; m < M_COUNT; m++) {
		unsigned x = (m % per_row) * bw, y = (r_box + (m / per_row) * 3) * CH;
		uint32_t bg = m_state[m] == 2 ? 0xc02020 : !m_state[m] ? 0x303030 : m == m_last ? 0xe0b000 : 0x1f8f3a;
		uint32_t fg = !m_state[m] ? 0x909090 : m_state[m] == 1 && m == m_last ? 0x000000 : 0xffffff;
		char t[24] = "";
		if (m_state[m]) {
			snprintf(t, sizeof(t), m_count[m] > 1 ? "%llu.%llus x%u" : "%llu.%llus", m_ms[m] / 1000, m_ms[m] / 100 % 10,
			    m_count[m]);
		}
		fill(x, y, bw - 4, 3 * CH - 4, bg);
		unsigned inner = (bw - 4) / CW;
		text_at(x + 8, y + 8, m_name[m], inner > 1 ? inner - 1 : 0, fg, bg);
		text_at(x + 8, y + 8 + CH, t, inner > 1 ? inner - 1 : 0, fg, bg);
	}
}

static void
draw_partial(unsigned top, unsigned n, unsigned count, const char *partial)
{
	char line[MAXCOLS];
	snprintf(line, sizeof(line), "%c%s", partial ? '>' : ' ', partial ? partial : "");
	row_text(top + count % n, line, 0x60a0ff, 0x101828);
}

/* a wrap-around panel: entry i at row i % n, '>' on the newest, a blank row after it */
static void
draw_ring(unsigned top, unsigned n, char (*ring)[MAXCOLS], unsigned count, const char *partial, uint32_t fg)
{
	if (!n) {
		return;
	}
	unsigned first = count > n - 1 ? count - (n - 1) : 0;
	for (unsigned i = first; i < count; i++) {
		char line[MAXCOLS];
		snprintf(line, sizeof(line), "%c%s", i + 1 == count ? '>' : ' ', ring[i % RING]);
		row_text(top + i % n, line, i + 1 == count ? 0xffffff : fg, 0x000000);
	}
	draw_partial(top, n, count, partial);
}

static void
draw_proc(unsigned i)
{
	unsigned per_row = cols / 25;
	if (!per_row || !n_procrows) {
		return;
	}
	unsigned cell = i % (per_row * n_procrows);
	char s[32];
	snprintf(s, sizeof(s), "%5d %.18s", pr[i % PROCS].pid, pr[i % PROCS].name);
	text_at((cell % per_row) * 25 * CW, (r_procs + cell / per_row) * CH, s, 25, p_color[pr[i % PROCS].state], 0x000000);
}

static void
draw_all(bool clear)
{
	if (clear) {
		fill(0, 0, fb_w, fb_h, 0x000000);
	}
	draw_title();
	draw_boxes();
	row_text(r_now, now, 0xffffff, 0x202020);
	for (unsigned i = 0; i < PINS; i++) {
		row_text(r_now + 1 + i, pin[i], 0xffe080, 0x202020);
	}
	row_text(r_events - 1, "-- events: kernel stages, userland milestones, failed exits, L = launchd lines", 0x60a0ff, 0x000000);
	draw_ring(r_events, n_events, ev, ev_n, NULL, 0xc0c0c0);
	row_text(r_procs - 1, "-- processes: green running, grey exit 0, red failed, yellow signature refused", 0x60a0ff, 0x000000);
	unsigned first = pr_n > PROCS ? pr_n - PROCS : 0;
	for (unsigned i = first; i < pr_n; i++) {
		draw_proc(i);
	}
	row_text(r_log - 1, "-- console", 0x60a0ff, 0x000000);
	draw_ring(r_log, n_log, lg, lg_n, cur, 0xa0a0a0);
}

static volatile int log_dirty;   /* console lines since the log panel was last drawn */

static bool
lock(void)
{
	/* yield_wanted: the display driver waits for the panel, so no new draw starts (a full redraw on the uncached GOP takes
	 * ~100-200 ms, longer than the driver's wait: rb5 copy NotReady, then leaf 345, 2026-11-14; as gts7xlwifi yield_requested). */
	return fb && !__atomic_load_n(&yield_wanted, __ATOMIC_ACQUIRE) && !__atomic_exchange_n(&draw_lock, 1, __ATOMIC_ACQUIRE);
}

static void
unlock(void)
{
	__atomic_store_n(&draw_lock, 0, __ATOMIC_RELEASE);
}

/* run a partial redraw now, or leave it to the monitor when the screen is busy (nested hook, other CPU) */
#define DRAW(body) do { if (lock()) { if (dirty) { dirty = 0; draw_all(false); } else { body; } unlock(); } else { dirty = 1; } } while (0)

/* ---- recording ---- */

static void
event(const char *s)
{
	uint64_t t = ms();
	last_event_ms = t;
	snprintf(ev[ev_n % RING], MAXCOLS, "%5llu.%03llu %s", t / 1000, t % 1000, s);
	if (ramoops) {
		char line[MAXCOLS + 8];
		int n = snprintf(line, sizeof(line), "\n[ev] %s\n", ev[ev_n % RING]);
		zone_put(line, n > 0 && (unsigned)n < sizeof(line) ? (unsigned)n : 0);
	}
	ev_n++;
	DRAW(draw_ring(r_events, n_events, ev, ev_n, NULL, 0xc0c0c0));
}

static void
milestone(unsigned m, bool failed)
{
	m_state[m] = failed ? 2 : 1;
	m_ms[m] = ms();
	if (!failed) {
		m_count[m]++;     /* xN on a box: reached N times (a restarted daemon) */
		m_last = m > m_last ? m : m_last;
	}
	DRAW(draw_boxes());
}

static void
set_pin(unsigned i, const char *s)
{
	strlcpy(pin[i], s, MAXCOLS);
	DRAW(row_text(r_now + 1 + i, pin[i], 0xffe080, 0x202020));
}

void
boot_progress_init(void)
{
	unsigned value = 0;
	if (!PE_parse_boot_argn("boot-progress", &value, sizeof(value)) || !value) {
		return;
	}
	PE_parse_boot_arg_str("build-tag", tag, sizeof(tag));
	PE_parse_boot_argn("ruan-ramoops", &ramoops, sizeof(ramoops));
	enabled = 1;
	milestone(M_KERNEL, false);
}

int
boot_progress_active(void)
{
	return enabled;
}

/* The OS takes the panel (package/LegacyDisplayProbe.cpp, before its first CPU copy into the scanout): stop drawing for
 * the rest of the boot, so the page never paints over SpringBoard. Always succeeds (see below). */

/* ---- crash banner after the hand-off (as UniXNU-fuxi crash_banner) ----
 * Once the display driver owns the panel the page is gone; the monitor thread then paints the bottom rows of the live
 * screen: milestones and copies, the last signal crash (BootFaultProbe.c), the SIGABRT text and the last two failed exits.
 * Each CPU copy (LegacyDisplayProbe.cpp) overwrites the frame, so it repaints after a copy or when a record changed, at most
 * once a second. boot-progress-banner=0 switches it off. */
extern void boot_progress_exit_fault(int, unsigned, char *, unsigned long);
extern void boot_progress_exit_reason(int, unsigned, char *, unsigned long);
extern volatile uint64_t native_legacy_copy_n __attribute__((weak_import));
/* swap flow (LegacyDisplayProbe.cpp, NativeLegacyDisplay): accepted/rejected swaps, retirements (swapstat[11]), vsync
 * messages sent/idle, family swap timeouts. accepted > copies + rejected means swaps wait unretired; accepted == copies with
 * vsync still counting means the compositor simply has nothing new to draw. */
extern volatile uint32_t native_legacy_swap_accepted_count __attribute__((weak_import));
extern volatile uint32_t native_legacy_swap_rejected_count __attribute__((weak_import));
extern volatile uint32_t native_legacy_swapstat[16] __attribute__((weak_import));
extern volatile uint64_t native_legacy_vsync_events[6] __attribute__((weak_import));
extern volatile uint64_t native_legacy_swap_timeouts __attribute__((weak_import));
static volatile uint32_t *ban_fb;
static char ban_crash[400], ban_reason[400], ban_exit[2][MAXCOLS];
static volatile unsigned ban_seq, ban_exits;

int
boot_progress_prepare_scanout(void)
{
	/* The display driver takes the panel for good. Never wait for draw_lock: its holder is any thread that printed to the
	 * console (log mirror), often at user priority, and on one CPU it can stay preempted for seconds while holding it (rb6:
	 * the copy refused even after 2 s, prep=1, then leaf 345, 2026-11-14). yield_wanted stops every new draw at lock(); a
	 * draw already running finishes into the same memory and the next frame copy covers it. fb is cleared only when the
	 * lock is free: an in-flight draw still reads fb. */
	__atomic_store_n(&yield_wanted, 1, __ATOMIC_RELEASE);
	if (fb) {
		ban_fb = fb;   /* called before every copy: later calls find fb already NULL (rb9: banner never painted) */
	}
	yielded = 1;
	if (fb && !__atomic_exchange_n(&draw_lock, 1, __ATOMIC_ACQUIRE)) {
		fb = NULL;
		unlock();
	}
	return 1;
}

void
boot_progress_cancel_scanout(void)
{
	/* nothing to undo: prepare_scanout always succeeds and the page stays yielded */
}

void
boot_progress_bind(uintptr_t base, unsigned width, unsigned height, unsigned rowbytes, unsigned depth)
{
	if (!enabled || yielded || !base || depth != 32 || width < 320 || height < 480 || rowbytes < width * 4) {
		return;
	}
	if (fb == (volatile uint32_t *)base) {
		/* the same mapping: repaint, a console switch (-v text console enable) may have cleared the screen */
		if (lock()) {
			dirty = 0;
			draw_all(false);
			unlock();
		}
		return;
	}
	/* bounded: a drawing thread preempted on this CPU must not hang the console switch */
	for (unsigned spin = 0; spin < 10000000 && __atomic_exchange_n(&draw_lock, 1, __ATOMIC_ACQUIRE); spin++) {
	}
	bool first = fb == NULL;
	fb = (volatile uint32_t *)base;
	fb_w = width, fb_h = height, fb_stride = rowbytes / 4;
	cols = width / CW > MAXCOLS - 2 ? MAXCOLS - 2 : width / CW;
	rows = height / CH;
	r_box = 1, r_now = 7;
	unsigned rest = rows > 17 ? rows - 11 - PINS : 3;
	n_events = rest * 3 / 10 < RING ? rest * 3 / 10 : RING;
	n_procrows = rest * 3 / 10;
	n_log = rest - n_events - n_procrows < RING ? rest - n_events - n_procrows : RING;
	r_events = r_now + 2 + PINS, r_procs = r_events + n_events + 1, r_log = r_procs + n_procrows + 1;
	if (first) {
		m_state[M_SCREEN] = 1, m_ms[M_SCREEN] = ms(), m_count[M_SCREEN] = 1, m_last = M_SCREEN;
	}
	dirty = 0;
	draw_all(true);
	unlock();
}

/* launchd's console lines about backboardd and about why it holds jobs (bootstrap/on-demand mode, boot tasks, restore
 * environment), copied to the events panel: the console ring scrolls them away within seconds. Matched on the whole line
 * (the console panel wraps it); the "com.apple.xpc.launchd|date time " prefix is dropped, two event rows at most. */
static const char *const mirror_key[] = {"backboard", "bootstrap mode", "ondemand mode", "initial on-demand",
	                                 "Restore environment", "oot task", "oot-task", "Conclave", "Early boot"};
static char full[512];
static unsigned full_len, mirrored;

static void
mirror_line(void)
{
	full[full_len] = 0;
	if (strnstr(full, "MOUNT-BY-ROLE", sizeof(full)) || strnstr(full, "mount_by_role", sizeof(full))) {
		set_pin(1, full);
	}
	bool hit = false;
	for (unsigned k = 0; k < sizeof(mirror_key) / sizeof(mirror_key[0]) && !hit; k++) {
		hit = strnstr(full, mirror_key[k], sizeof(full)) != NULL;
	}
	if (!hit || mirrored >= 40) {
		return;
	}
	mirrored++;
	const char *p = strnstr(full, " (", sizeof(full)), *s = strncmp(full, "com.apple.xpc.launchd", 21) || !p ? full : p + 1;
	char line[MAXCOLS];
	for (unsigned part = 0; part < 2 && *s; part++) {
		size_t n = strlen(s) > 84 ? 84 : strlen(s);
		snprintf(line, sizeof(line), "%s%.*s", part ? "  .." : "L ", (int)n, s);
		event(line);
		s += n;
	}
}

void
boot_progress_putc(char c)
{
	if (!enabled) {
		return;
	}
	if (c != '\0') {
		zone_put(&c, 1);
	}
	if (c == '\n') {
		mirror_line();
		full_len = 0;
	} else if (full_len < sizeof(full) - 1 && c != '\r' && c != '\0') {
		full[full_len++] = (c == '\t' || (unsigned char)c < 0x20) ? ' ' : c;
	}
	if (c == '\n' || cur_len >= (cols ? cols : MAXCOLS) - 2) {
		cur[cur_len] = 0;
		strlcpy(lg[lg_n % RING], cur, MAXCOLS);
		lg_n++;
		cur_len = 0;
		cur[0] = 0;
		log_dirty = 1;   /* drawn by monitor(): a ring redraw is ~1.3M uncached stores, too slow for every console line */
		if (c == '\n') {
			return;
		}
	}
	if (c == '\r' || c == '\0') {
		return;
	}
	cur[cur_len++] = (c == '\t' || (unsigned char)c < 0x20) ? ' ' : c;
	cur[cur_len] = 0;
}

void
boot_progress_stage(const char *s)
{
	if (!enabled || !s) {
		return;
	}
	strlcpy(now, s, sizeof(now));
	size_t len = strlen(now);
	if (len && now[len - 1] == '\n') {
		now[len - 1] = 0;
	}
	for (unsigned m = 0; m < M_COUNT; m++) {
		if (m_stage[m] && !strcmp(now, m_stage[m]) && !m_state[m]) {
			milestone(m, false);
		}
	}
	DRAW(row_text(r_now, now, 0xffffff, 0x202020));
	if (!strncmp(now, "ram-data", 8)) {
		set_pin(0, now);
	}
	event(now);
}

static unsigned
proc_slot(int pid)
{
	unsigned first = pr_n > PROCS ? pr_n - PROCS : 0;
	for (unsigned i = pr_n; i-- > first;) {
		if (pr[i % PROCS].pid == pid) {
			return i;
		}
	}
	return UINT32_MAX;
}

void
boot_progress_process_stage(int pid, const char *name, const char *stage)
{
	bool accepted = !strcmp(stage, "exec process signature accepted");
	bool refused = !strcmp(stage, "exec process signature REFUSED") || !strcmp(stage, "exec MAC policy REFUSED");
	if (!enabled || (!accepted && !refused)) {
		return;
	}
	unsigned i = proc_slot(pid);
	if (i == UINT32_MAX) {
		i = pr_n++;
	}
	pr[i % PROCS].pid = pid;
	pr[i % PROCS].state = refused ? P_REFUSED : P_RUN;
	strlcpy(pr[i % PROCS].name, name ? name : "?", sizeof(pr[0].name));
	execs++;
	DRAW(draw_proc(i));
	char line[MAXCOLS];
	if (refused) {
		snprintf(line, sizeof(line), "%s[%d] %s", name, pid, stage);
		event(line);
		return;
	}
	unsigned m = pid == 1 ? M_LAUNCHD : !strcmp(name, "backboardd") ? M_BACKBOARDD :
	    !strcmp(name, "SpringBoard") ? M_SPRINGBOARD : !m_state[M_DAEMONS] ? M_DAEMONS : M_COUNT;
	if (m != M_COUNT) {
		milestone(m, false);
		snprintf(line, sizeof(line), "exec %s[%d] -> %s", name, pid, m_name[m]);
		event(line);
	}
}

void
boot_progress_exit(int pid, const char *name, int rv, unsigned ns, uint64_t code)
{
	if (!enabled) {
		return;
	}
	exits++;
	unsigned i = proc_slot(pid);
	if (i != UINT32_MAX) {
		pr[i % PROCS].state = rv ? P_FAIL : P_EXIT0;
		DRAW(draw_proc(i));
	}
	unsigned m = pid == 1 ? M_LAUNCHD : !strcmp(name, "backboardd") ? M_BACKBOARDD :
	    !strcmp(name, "SpringBoard") ? M_SPRINGBOARD : M_COUNT;
	if (m != M_COUNT) {
		milestone(m, true);
	}
	if (rv || m != M_COUNT) {
		char line[MAXCOLS];
		snprintf(line, sizeof(line), "exit %s[%d] status 0x%x reason ns %u code 0x%llx", name, pid, rv, ns, code);
		event(line);
		if (rv) {
			strlcpy(ban_exit[ban_exits++ % 2], line, MAXCOLS);
		}
	}
	/* signal crashes: fault PC/LR/ESR/FAR + backtrace (BootFaultProbe.c, fuxi), and for SIGABRT the abort text found in the
	 * process's heap. Shown as events now and on the banner after the hand-off (the page is gone by then). */
	unsigned sig = (unsigned)rv & 127;
	if (sig >= 3 && sig <= 12 && sig != 9) {
		char text[400] = "";
		boot_progress_exit_fault(pid, sig, text, sizeof(text));
		if (text[0]) {
			strlcpy(ban_crash, text, sizeof(ban_crash));
			event(text);
		}
		if (sig == 6) {
			boot_progress_exit_reason(pid, sig, text, sizeof(text));
			if (text[0]) {
				strlcpy(ban_reason, text, sizeof(ban_reason));
				event(text);
			}
		}
		ban_seq++;
	}
	/* PID 1's exit ends in the initproc panic, whose screen covers the events; hold its thread here instead so the page
	 * (pid1 syscall lines, dyld's console lines) stays readable. Called from proc_prepareexit before any lock is taken. */
	if (pid == 1) {
		event("pid 1 exited: held here (boot-progress), no initproc panic");
		held_ms = held_ms ? held_ms : ms() | 1;
		for (;;) {
			assert_wait_timeout((event_t)&boot_progress_exit, THREAD_UNINT, 1000, NSEC_PER_MSEC);
			thread_block(THREAD_CONTINUE_NULL);
		}
	}
}

/* PID 1 syscalls (patches/xnu/ruan-pid1-dyld.patch): the first 16 that failed, plus every shared_region_check_np (294),
 * shared_region_map_and_slide_2_np (536) and fcntl F_ADDFILESIGS/_RETURN/F_CHECK_LV (92: 61/97/98), so a dyld stop before
 * main shows the call, its errno and the path it used. Line: "pid1 sc<code> e<errno> a<arg0>,<arg1> rv<rval> <path tail>". */

/* What a boot task or early daemon (pid < 64, patches/xnu/ruan-pid1-dyld.patch) writes to stdout/stderr: one "W name[pid] text"
 * event per line, 60 lines in all. mount -P exits 66 after printing why (e.g. "failed to get boot-manifest-hash"), and its
 * stderr reaches no console otherwise. */
extern void proc_selfname(char *buf, int size);

void
boot_progress_early_write(int pid, const uint64_t *arg)
{
	static unsigned shown;
	char buf[256], name[24], line[MAXCOLS];
	size_t len = arg[2] < sizeof(buf) - 1 ? (size_t)arg[2] : sizeof(buf) - 1;
	if (!enabled || shown >= 60 || (arg[0] != 1 && arg[0] != 2) || !len || copyin(arg[1], buf, len)) {
		return;
	}
	buf[len] = 0;
	proc_selfname(name, sizeof(name));
	for (char *s = buf, *e; *s && shown < 60; s = e) {
		for (e = s; *e && *e != '\n'; e++) {
		}
		char *next = *e ? e + 1 : e;
		*e = 0;
		if (*s) {
			shown++;
			snprintf(line, sizeof(line), "W %s[%d] %.88s", name, pid, s);
			event(line);
		}
		e = next;
	}
}

void
boot_progress_pid1_syscall(int code, int error, const uint64_t *arg, uint64_t rv)
{
	static unsigned shown;
	if ((code == 4 || code == 397) && !error) {
		boot_progress_early_write(1, arg);
		return;
	}
	bool cs = code == 92 && (arg[1] == 61 || arg[1] == 97 || arg[1] == 98);
	if (!enabled || shown >= 16 || error < 0 || (!error && code != 294 && code != 536 && !cs)) {
		return;
	}
	shown++;
	/* the path argument: openat/openat_nocancel/fstatat/fstatat64 take it second; open/access/getattrlist/stat64/lstat64 first */
	int at = (code == 463 || code == 464 || code == 469 || code == 470) ? 1 :
	    (code == 5 || code == 398 || code == 33 || code == 220 || code == 338 || code == 340) ? 0 : -1;
	char path[256] = "", line[MAXCOLS];
	vm_size_t done = 0;
	if (at >= 0 && copyinstr(arg[at], path, sizeof(path), &done)) {
		strlcpy(path, "?", sizeof(path));
	}
	size_t len = strlen(path);
	snprintf(line, sizeof(line), "pid1 sc%d e%d a%llx,%llx rv%llx %s", code, error, arg[0], arg[1], rv,
	    len > 56 ? path + len - 56 : path);
	event(line);
}

extern void ram_data_describe(char *, size_t) __attribute__((weak_import));

/* After the hand-off lock() refuses every drawer (yield_wanted); the banner takes draw_lock itself and points fb at the
 * panel for the length of one paint. */
/* boot-progress-banner: 0 off, 1 the full banner (9 rows), 2 the status row plus the two input rows (3 rows at the bottom). A row is
 * 100 glyphs of 16x32 32-bit stores into the scanout, about 51,000 stores. (display-perf/BootProgress-banner.patch, adapted.) */
static unsigned banner_mode = 1;
/* Written by package/RuanGpuPower.c (ruan-gpu=<n> or ruan-gpu-survey=1), whose strong definitions replace these empty weak ones. */
char ruan_gpu_row[128] __attribute__((weak)), ruan_gpu_short[32] __attribute__((weak));
/* package/UsbDebugCdc.cpp (ruan-usbdbg=1): its USB state ("usb e<events> r<resets> c<configured>[o = tty open]") or why it stopped. */
char ruan_usb_short[48] __attribute__((weak));
/* LegacyDisplayProbe.cpp: the last and the longest frame copy, in counter ticks (cntpct_el0, 19.2 MHz on ruan). */
extern volatile uint64_t native_legacy_copy_last __attribute__((weak_import));
extern volatile uint64_t native_legacy_copy_max __attribute__((weak_import));

static void
banner(void)
{
	static uint64_t painted_copies = UINT64_MAX;
	static unsigned painted_seq = UINT32_MAX, painted_exits = UINT32_MAX;
	static uint64_t painted_s = UINT64_MAX;
	uint64_t copies = &native_legacy_copy_n ? native_legacy_copy_n : 0;
	const uint64_t now_s = ms() / 1000;   /* the monitor ticks once a second: t= advances, so this repaints every tick */
	if (!ban_fb || (copies == painted_copies && ban_seq == painted_seq && ban_exits == painted_exits && now_s == painted_s) ||
	    __atomic_exchange_n(&draw_lock, 1, __ATOMIC_ACQUIRE)) {
		return;        /* nothing new, or a draw from before the hand-off is still running: next second */
	}
	painted_copies = copies, painted_seq = ban_seq, painted_exits = ban_exits, painted_s = now_s;
	char line[MAXCOLS];
	unsigned row = rows > 9 ? rows - 9 : 0;
	fb = ban_fb;
	ban_painting = 1;
	uint64_t hz = 0;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(hz));
	hz = hz ? hz / 1000 : 19200;
	const uint64_t cp_last = &native_legacy_copy_last ? native_legacy_copy_last / hz : 0;
	const uint64_t cp_max = &native_legacy_copy_max ? native_legacy_copy_max / hz : 0;
	if (banner_mode == 2) {
		row = rows > 3 ? rows - 3 : 0;
	}
	snprintf(line, sizeof(line), "bp t=%llus copies=%llu cp%llu/%llums exits=%u LD %c DM %c BB %c SB %c x%u sw a%u r%u ret%u vs%llu i%llu st%llu ar%llu to%llu",
	    ms() / 1000, copies, cp_last, cp_max, exits, "-+X"[m_state[M_LAUNCHD]], "-+X"[m_state[M_DAEMONS]], "-+X"[m_state[M_BACKBOARDD]],
	    "-+X"[m_state[M_SPRINGBOARD]], m_count[M_SPRINGBOARD],
	    &native_legacy_swap_accepted_count ? native_legacy_swap_accepted_count : 0,
	    &native_legacy_swap_rejected_count ? native_legacy_swap_rejected_count : 0,
	    &native_legacy_swapstat ? native_legacy_swapstat[11] : 0,
	    &native_legacy_vsync_events ? native_legacy_vsync_events[1] : 0,
	    &native_legacy_vsync_events ? native_legacy_vsync_events[2] : 0,
	    &native_legacy_vsync_events ? native_legacy_vsync_events[4] : 0,   /* st: the 60 Hz timer was created */
	    &native_legacy_vsync_events ? native_legacy_vsync_events[0] : 0,   /* ar: armed for a registered client */
	    &native_legacy_swap_timeouts ? native_legacy_swap_timeouts : 0);
	row_text(row++, line, 0x000000, 0xc0c0c0);
	if (banner_mode != 2) {
		for (unsigned part = 0; part < 3; part++, row++) {
			row_text(row, strlen(ban_crash) > part * (cols - 6) ? ban_crash + part * (cols - 6) : "", 0xff6060, 0x101010);
		}
		row_text(row++, ban_reason[0] || !ruan_gpu_row[0] ? ban_reason : ruan_gpu_row, 0xffa070, 0x101010);   /* survey line until an abort */
	}
	{	/* input (package/RuanInput.c): tp = touch samples, btn = button changes, hid = reports NativeHidInput sent;
		 * raw = the NT36532's last point and max its fw-info axes, n = the 0..65535 position posted; then each driver's last line */
		extern volatile uint32_t ruan_touch_events, ruan_button_events, ruan_buttons_mask, native_touch_hid_reports;
		extern volatile uint32_t ruan_touch_raw_x, ruan_touch_raw_y, ruan_touch_max_x, ruan_touch_max_y, ruan_touch_norm_x,
		    ruan_touch_norm_y;
		extern char ruan_input_row[96], ruan_buttons_row[96];
		/* HidInputProbe.cpp: hs = start stage (3 = done), r = last touch handleReport result (0 = taken), ev = event driver seen */
		extern volatile uint32_t native_hid_stage, native_hid_input_events[8];
		extern volatile int native_hid_input_results[8];
		snprintf(line, sizeof(line), "in tp%u hid%u r%x hs%u ev%u raw %u,%u max %u,%u n %u,%u | %s", ruan_touch_events,
		    native_touch_hid_reports, native_hid_input_results[6], native_hid_stage, native_hid_input_events[3],
		    ruan_touch_raw_x, ruan_touch_raw_y, ruan_touch_max_x, ruan_touch_max_y, ruan_touch_norm_x, ruan_touch_norm_y, ruan_input_row);
		row_text(row++, line, 0x80ffff, 0x101010);
		/* package/RuanGpuPower.c (ruan-gpu=<n>): the GPU stage summary, so a photo after the hand-off has it */
		snprintf(line, sizeof(line), "%s%s%s%sbtn%u m%x | %s", ruan_usb_short, ruan_usb_short[0] ? " " : "",
		    ruan_gpu_short, ruan_gpu_short[0] ? " " : "",
		    ruan_button_events, ruan_buttons_mask, ruan_buttons_row);
		row_text(row++, line, 0x80ffff, 0x101010);
	}
	if (banner_mode != 2) {
		row_text(row++, ban_exit[(ban_exits + 1) % 2], 0xffe060, 0x101010);
		row_text(row, ban_exit[ban_exits % 2], 0xffe060, 0x101010);
	}
	ban_painting = 0;
	fb = NULL;
	unlock();
}

static void
monitor(void *arg __unused, wait_result_t wr __unused)
{
	unsigned banner_on = 1;
	PE_parse_boot_argn("boot-progress-banner", &banner_on, sizeof(banner_on));
	banner_mode = banner_on;
	for (unsigned tick = 0;; tick++) {
		if (yielded && banner_on) {
			banner();
		}
		DRAW(draw_title(); if (n_log && log_dirty) { log_dirty = 0; draw_ring(r_log, n_log, lg, lg_n, cur, 0xa0a0a0); } else if (n_log) draw_partial(r_log, n_log, lg_n, cur));
		if (&ram_data_describe && m_state[M_LAUNCHD] && tick % 5 == 0) {
			char line[MAXCOLS];
			ram_data_describe(line, sizeof(line));
			if (strcmp(line, pin[2])) {
				set_pin(2, line);
			}
		}
		assert_wait_timeout((event_t)&monitor, THREAD_UNINT, 1000, NSEC_PER_MSEC);
		thread_block(THREAD_CONTINUE_NULL);
	}
}

/* ruan-autoreset=<seconds> (unattended test runs): <seconds> after a boot-progress hold, or ruan-autoreset-max (default 600)
 * seconds after start without one, the tablet restarts into fastboot (package/BootReset.c, from UniXNU-Dizi-Ruan): the PMIC
 * reboot-reason cell gets "bootloader" at once, so a Gunyah watchdog bite after a panic or hang (no pings for 60 s), or a long
 * power press, also ends in fastboot. The ramoops zone is a device mapping written with dsb sy: already in DRAM, no flush. */
extern int boot_reset_probe(char *, unsigned);
extern int boot_reset_mark_bootloader(char *, unsigned);
extern int boot_reset_watchdog(uint32_t, char *, unsigned);
extern int boot_reset_bootloader(char *, unsigned);
static unsigned autoreset, autoreset_max = 600;

static void
autoreset_thread(void *arg __unused, wait_result_t wr __unused)
{
	char text[200], line[MAXCOLS];
	const uint64_t start = ms();
	int rc = boot_reset_probe(text, sizeof(text));
	event(text);
	if (rc) {
		event("autoreset: off, the reboot-reason cell is not writable");
		return;
	}
	boot_reset_mark_bootloader(text, sizeof(text));
	event(text);
	/* The Gunyah watchdog bit at ~60 s although pinged (rbar2, 2026-11-14: fastboot 84-87 s after continue): opt-in only. */
	unsigned wdt = 0;
	PE_parse_boot_argn("ruan-autoreset-wdt", &wdt, sizeof(wdt));
	if (wdt) {
		boot_reset_watchdog(autoreset_max + autoreset, text, sizeof(text));
		event(text);
	}
	while (!(held_ms && ms() - held_ms >= autoreset * 1000ULL) && ms() - start < autoreset_max * 1000ULL) {
		assert_wait_timeout((event_t)&autoreset, THREAD_UNINT, 1000, NSEC_PER_MSEC);
		thread_block(THREAD_CONTINUE_NULL);
	}
	snprintf(line, sizeof(line), "autoreset: %s, restarting into fastboot", held_ms ? "held" : "max time");
	event(line);
	boot_reset_bootloader(text, sizeof(text));   /* returns only when refused */
	event(text);
}

extern void ruan_cpufreq_start(void);   /* package/RuanCpuFreq.c, ruan-cpufreq=<n>; strong: a weak import would not pull it from the archive */

void
boot_progress_start(void)
{
	thread_t thread;
	ruan_cpufreq_start();
	extern void ruan_gpu_survey(void);
	ruan_gpu_survey();   /* package/RuanGpuPower.c: ruan-gpu=<1-3> (gpu-dev stage S1), ruan-gpu-survey=1 = mode 1; nothing otherwise */
	if (enabled) {
		zone_map();
		char line[MAXCOLS];
		snprintf(line, sizeof(line), "mem win 0x%lx+%luM out 0x%llx-0x%llx adopted %up refused %up max %lluM",
		    gPhysBase, real_phys_size >> 20, arm_vm_outside_base, arm_vm_outside_end, ml_outside_memory_pages,
		    ml_outside_memory_refused, max_mem >> 20);
		event(line);
	}
	if (enabled && kernel_thread_start_priority(monitor, NULL, MAXPRI_KERNEL, &thread) == KERN_SUCCESS) {
		thread_set_thread_name(thread, "boot-progress");
		thread_deallocate(thread);
	}
	/* Touch and buttons (package/RuanInput.c): each driver checks its own boot-arg (ruan_touch=1, garnet_buttons=1). */
	extern void ruan_input_start(void);
	ruan_input_start();
	PE_parse_boot_argn("ruan-autoreset-max", &autoreset_max, sizeof(autoreset_max));
	if (enabled && PE_parse_boot_argn("ruan-autoreset", &autoreset, sizeof(autoreset)) && autoreset &&
	    kernel_thread_start_priority(autoreset_thread, NULL, MAXPRI_KERNEL, &thread) == KERN_SUCCESS) {
		thread_set_thread_name(thread, "autoreset");
		thread_deallocate(thread);
	}
}

void
boot_progress_irq(uint64_t pc __unused, uint64_t cpsr __unused, uint64_t sp __unused)
{
	irqs++;
}

void
boot_progress_poll(void)
{
}

/* boot_progress_user_breakpoint/_abort (EL0 trap records) are in package/BootFaultProbe.c. */

/* A critical process (a launchd boot task with RequireSuccess, e.g. mount[3]) exited: kern_exit.c would panic next, and the
 * panic text covers the events with the boot task's own output (W lines). Hold this thread instead, as for PID 1. */
void
boot_progress_critical_exit(int pid __unused, char *buf, unsigned long len __unused)
{
	if (!enabled) {
		return;
	}
	char line[MAXCOLS];
	snprintf(line, sizeof(line), "critical %s: held here (boot-progress), no panic", buf);
	event(line);
	held_ms = held_ms ? held_ms : ms() | 1;
	for (;;) {
		assert_wait_timeout((event_t)&boot_progress_critical_exit, THREAD_UNINT, 1000, NSEC_PER_MSEC);
		thread_block(THREAD_CONTINUE_NULL);
	}
}

/*
 * ruan: glue between HakiOS's touch and button drivers (RuanTouch.c: NT36532 on QUP SE 0xa8c000, bit-banged SPI;
 * RuanButtons.c: PMK8350 PON + PMIC GPIO through the SPMI arbiter's observer channels, read only) and UniXNU's
 * NativeHidInput (ShengHidInput, from UniXNU-j716f): the finger set under the sequence lock NativeHidInput reads
 * (native_touch_*, j716f TouchState.cpp) and its report-2 button mask (bit 1 power, 2 volume up, 3 volume down).
 * ruan_input_start() (from boot_progress_start) starts both drivers; they parse their own boot-args
 * (ruan_touch=1, garnet_buttons=1 ruan=1).
 */
#include <stdint.h>
#include <string.h>
#include <kern/locks.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include "RuanInputShim.h"

volatile uint32_t native_touch_seq, native_touch_count, native_touch_hid_reports;
volatile int native_touch_xs[12], native_touch_ys[12], native_touch_ids[12];
volatile uint32_t ruan_touch_events, ruan_button_events, ruan_buttons_mask, ruan_input_lines, ruan_key_presses[3];
volatile uint32_t ruan_touch_raw_x, ruan_touch_raw_y, ruan_touch_max_x, ruan_touch_max_y, ruan_touch_norm_x, ruan_touch_norm_y;
volatile uint32_t ruan_touch_multi, ruan_touch_maxfingers, ruan_touch_lastmulti[4];   /* reports with >= 2 fingers, the most at once, last such report: ids and two positions */
char ruan_input_row[96];
char ruan_buttons_row[96];   /* RuanButtons.c's last log line (it prints through loader_log_putc; RuanTouch.c uses loader_log_line) */

/* Display power state (macOS/docs/research/power/plan.md). RuanBacklightSvc.cpp calls ruan_screen_set when the backlight goes to or
 * leaves level 0 (CoreBrightness on the power button). ruan_screen_off: RuanCpuFreq.c caps both CPU domains at their second-lowest
 * level and RuanGpuPower.c's DCVS at its floor. ruan_sleeping (ruan-sleep=1 and the screen off, suspend-to-idle stage 1): the
 * lowest CPU levels, idle cores bounded by ruan-sleep-wfi-us (default 10000) instead of ruan-idle-wfi-us
 * (patches/xnu/ruan-idle-wfi.patch), the touch thread reads only on its interrupt, the buttons every 50 ms. The power key still
 * reaches SpringBoard, which turns the backlight on again: that is the wake. */
volatile uint32_t ruan_screen_off, ruan_sleeping, ruan_screen_changes;
extern uint32_t ruan_idle_wfi_sleep_us;   /* patches/xnu/ruan-idle-wfi.patch */

void ruan_screen_set(int off);
void
ruan_screen_set(int off)
{
	static uint32_t parsed, sleep_mode, sleep_wfi_us = 10000;
	if (!parsed) {   /* one caller: the backlight work loop */
		PE_parse_boot_argn("ruan-sleep", &sleep_mode, sizeof(sleep_mode));
		PE_parse_boot_argn("ruan-sleep-wfi-us", &sleep_wfi_us, sizeof(sleep_wfi_us));
		parsed = 1;
	}
	if ((uint32_t)(off != 0) == ruan_screen_off) {
		return;
	}
	ruan_sleeping = off && sleep_mode == 1;
	ruan_idle_wfi_sleep_us = ruan_sleeping ? sleep_wfi_us : 0;
	ruan_screen_off = off != 0;
	ruan_screen_changes++;
}

static void (*volatile touch_sink)(void *), *volatile touch_context;
static void (*volatile buttons_sink)(void *, uint32_t);
static void *volatile buttons_context;

void native_touch_set_sink(void (*sink)(void *), void *context);
void native_buttons_set_sink(void (*sink)(void *, uint32_t), void *context);
void ruan_input_start(void);
void hakios_tl(const char *format, ...);
void loader_log_line(const char *line);
void loader_log_putc(char c);

void
native_touch_set_sink(void (*sink)(void *), void *context)
{
	__atomic_store_n(&touch_sink, (void (*)(void *))0, __ATOMIC_RELEASE);
	__atomic_store_n(&touch_context, context, __ATOMIC_RELEASE);
	__atomic_store_n(&touch_sink, sink, __ATOMIC_RELEASE);
}

void
native_buttons_set_sink(void (*sink)(void *, uint32_t), void *context)
{
	__atomic_store_n(&buttons_sink, (void (*)(void *, uint32_t))0, __ATOMIC_RELEASE);
	__atomic_store_n(&buttons_context, context, __ATOMIC_RELEASE);
	__atomic_store_n(&buttons_sink, sink, __ATOMIC_RELEASE);
}

/* NativeHidInput maps x over 0..30480 and y over 0..20320 to its 0..32767 report range (j716f TouchState.cpp). */
#define FINGERS 10
static struct { int down, x, y; } contact[FINGERS];

void
hakios_touch_post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y)
{
	if (type == HAKIOS_BUTTON_DOWN || type == HAKIOS_BUTTON_UP) {
		uint32_t bit = finger == HAKIOS_BUTTON_LOCK ? 2 : finger == HAKIOS_BUTTON_VOLUME_UP ? 4 :
		    finger == HAKIOS_BUTTON_VOLUME_DOWN ? 8 : 0;
		uint32_t mask = type == HAKIOS_BUTTON_DOWN ? (ruan_buttons_mask | bit) : (ruan_buttons_mask & ~bit);
		ruan_buttons_mask = mask;
		ruan_button_events++;
		void (*sink)(void *, uint32_t) = __atomic_load_n(&buttons_sink, __ATOMIC_ACQUIRE);
		if (sink) {
			sink(__atomic_load_n(&buttons_context, __ATOMIC_ACQUIRE), mask);
		}
		return;
	}
	if (finger >= FINGERS) {
		return;
	}
	ruan_touch_events++;
	ruan_touch_norm_x = x, ruan_touch_norm_y = y;
	contact[finger].down = type != HAKIOS_TOUCH_UP;
	contact[finger].x = (int)(((uint64_t)(x > 65535 ? 65535 : x) * 30479) / 65535);
	contact[finger].y = (int)(((uint64_t)(y > 65535 ? 65535 : y) * 20319) / 65535);
	/* One producer thread (RuanTouch.c): the sequence lock only guards the reader. */
	native_touch_seq = native_touch_seq + 1u;
	__asm__ volatile ("dmb ish" ::: "memory");
	unsigned n = 0;
	for (unsigned i = 0; i < FINGERS; i++) {
		if (contact[i].down) {
			native_touch_ids[n] = (int)i;
			native_touch_xs[n] = contact[i].x;
			native_touch_ys[n] = contact[i].y;
			n++;
		}
	}
	native_touch_count = n;
	__asm__ volatile ("dmb ish" ::: "memory");
	native_touch_seq = native_touch_seq + 1u;
	void (*sink)(void *) = __atomic_load_n(&touch_sink, __ATOMIC_ACQUIRE);
	if (sink) {
		sink(__atomic_load_n(&touch_context, __ATOMIC_ACQUIRE));
	}
}

/* HakiOS's loader log: the last line is shown on the boot-progress banner. */
void
loader_log_line(const char *line)
{
	strlcpy(ruan_input_row, line, sizeof(ruan_input_row));
	size_t n = strlen(ruan_input_row);
	if (n && ruan_input_row[n - 1] == '\n') {
		ruan_input_row[n - 1] = 0;
	}
	ruan_input_lines++;
}

void
loader_log_putc(char c)
{
	static unsigned at;
	static char building[sizeof(ruan_input_row)];
	if (c == '\n' || at == sizeof(building) - 1) {
		building[at] = 0;
		at = 0;
		strlcpy(ruan_buttons_row, building, sizeof(ruan_buttons_row));
		return;
	}
	building[at++] = c;
}

void
hakios_tl(const char *format, ...)
{
	(void)format;
}

/* RuanButtons.c (power key, now on by default) and RuanBattery.c both read through the arbiter: one transfer at a time.
 * shortcut: spins without disabling preemption (a hold is ~10 us, at most the 2 ms read timeout). */
static volatile bool spmi_busy;

void
hakios_spmi_lock(void)
{
	while (__atomic_test_and_set(&spmi_busy, __ATOMIC_ACQUIRE)) {
	}
}

void
hakios_spmi_unlock(void)
{
	__atomic_clear(&spmi_busy, __ATOMIC_RELEASE);
}

void
ruan_input_start(void)
{
	extern void ruan_battery_init(void);
	hakios_focaltech_init();
	hakios_buttons_init();
	ruan_battery_init();
}

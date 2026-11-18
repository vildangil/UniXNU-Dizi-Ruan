// SPDX-License-Identifier: BSD-2-Clause-Patent
/* Stand-ins for the ruan drivers that package/BootProgressRuan.c reports on but dizi does not have yet (touch, buttons,
 * HID input, legacy display, memory outside the window, boot reset, fault records, RAM Data). Counters read 0 and
 * rows are empty; functions do nothing. Replace each with the real driver when it is ported. */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* arm_vm_outside_base/end and ml_outside_memory_pages/refused come from patches/xnu/dizi-memory-outside.patch. */

/* The native_legacy_* display counters come from package/LegacyDisplayProbe.cpp and GopFramebuffer NativeLegacyDisplay. */

volatile uint32_t ruan_touch_events, ruan_button_events, ruan_buttons_mask, native_touch_hid_reports;
volatile uint32_t ruan_touch_raw_x, ruan_touch_raw_y, ruan_touch_max_x, ruan_touch_max_y, ruan_touch_norm_x, ruan_touch_norm_y;
char ruan_input_row[96], ruan_buttons_row[96];
volatile uint32_t native_hid_stage, native_hid_input_events[8];
volatile int native_hid_input_results[8];

void ruan_cpufreq_start(void) {}
void ruan_gpu_survey(void) {}
void ruan_input_start(void) {}
void ram_data_describe(char *text, size_t size) { if (text && size) text[0] = 0; }

int boot_reset_probe(char *text, unsigned size) { (void)size; if (text) text[0] = 0; return 0; }
int boot_reset_mark_bootloader(char *text, unsigned size) { (void)size; if (text) text[0] = 0; return 0; }
int boot_reset_watchdog(uint32_t seconds, char *text, unsigned size) { (void)seconds; (void)size; if (text) text[0] = 0; return 0; }
int boot_reset_bootloader(char *text, unsigned size) { (void)size; if (text) text[0] = 0; return 0; }

void boot_progress_exit_fault(int pid, unsigned code, char *name, unsigned long address) { (void)pid; (void)code; (void)name; (void)address; }
void boot_progress_exit_reason(int pid, unsigned code, char *name, unsigned long value) { (void)pid; (void)code; (void)name; (void)value; }
void boot_progress_user_abort(void *state, unsigned esr, uint64_t far) { (void)state; (void)esr; (void)far; }
void boot_progress_user_breakpoint(void *state, unsigned esr) { (void)state; (void)esr; }

/* NativeRamBlock (Data seed) weak-imports this to hand the loader's packed seed pages back to the VM; dizi's XNU has no
 * such hook, and the static kernel link needs a definition. false = keep the boot memory (ruan's RamBlockNoStore.c). */
bool ml_static_mfree_prepare(uintptr_t address, size_t size) { (void)address; (void)size; return false; }

// SPDX-License-Identifier: BSD-2-Clause-Patent
/* Stand-ins for the parts of the ruan port that dizi does not build (scripts/build-boot-progress-ruan.py): its RAM root
 * (RamRootProbe.c), the Adreno 710 bring-up (RuanGpuPower.c, AdrenoHfi.c) and the Wi-Fi/audio status stubs. Counters read 0,
 * rows are empty and functions report "not available", so the boot-progress page, the USB debug link and the display probe
 * link without them. Touch, buttons, battery, backlight, CPU frequency, boot reset and the crash banner are the real ruan code. */
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

/* RAM root (ruan only): dizi's Data volume comes from dizi-data-volume.patch. */
void ram_data_describe(char *text, size_t size) { if (text && size) text[0] = 0; }

/* Adreno 710 (ruan's experimental GPU stages): not built on dizi. */
void ruan_gpu_survey(void) {}

/* NativeRamBlock (Data seed) weak-imports this to hand the loader's packed seed pages back to the VM; dizi's XNU has no
 * such hook, and the static kernel link needs a definition. false = keep the boot memory (ruan's RamBlockNoStore.c). */
bool ml_static_mfree_prepare(uintptr_t address, size_t size) { (void)address; (void)size; return false; }

/* Adreno 710 entry points that the display probe, the boot-progress page and the USB debug link call; on dizi none of them
 * does anything: "not ready", no mapping, no blit, so every frame keeps the CPU copy (fb-wc=1). */
int ruan_gpu_is_s5_ready(void) { return 0; }
int ruan_gpu_run(unsigned mode, int (*trace)(void *, const char *), void *ctx) { (void)mode; (void)trace; (void)ctx; return -1; }
int ruan_gpu_stream0_map_page(uint32_t va, uint64_t pa, uint32_t bytes) { (void)va; (void)pa; (void)bytes; return -1; }
void ruan_gpu_stream0_tlb_flush(void) {}
int ruan_gpu_dma_blit_frame(uint32_t src, uint32_t dst, uint32_t dwords) { (void)src; (void)dst; (void)dwords; return -1; }
uint32_t ruan_gpu_ring_wraps(void) { return 0; }
void ruan_gpu_set_firmware(const void *data, size_t size) { (void)data; (void)size; }
void ruan_gpu_set_sqe_firmware(const void *data, size_t size) { (void)data; (void)size; }

/* The Adreno accelerator (Metal discovery): LegacyDisplayProbe.cpp publishes it only with ruan-metal=1 (dizi guard). */
void native_adreno_accelerator_static_init(void) __asm__("__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp");
void native_adreno_accelerator_static_init(void) {}
void *native_adreno_accelerator_allocate(void) { return NULL; }
unsigned native_adreno_accelerator_instance_size(void) { return 0; }
void *native_adreno_user_client_create(void *task, void *id, uint32_t type, void *props) { (void)task; (void)id; (void)type; (void)props; return NULL; }

/* Wi-Fi and audio: ruan's own review calls its probes status stubs that touch no hardware; dizi reports them as absent. */
void ruan_wifi_init(void) {}
const char *ruan_wifi_status_str(void) { return "not ported"; }
void ruan_audio_init(void) {}
const char *ruan_audio_status_str(void) { return "not ported"; }

/* RuanInput.c sets this when the screen sleeps (ruan-sleep=1); ruan's patches/xnu/ruan-idle-wfi.patch reads it in the idle loop.
 * dizi does not carry that opt-in patch, so nothing reads it here. */
uint32_t ruan_idle_wfi_sleep_us;

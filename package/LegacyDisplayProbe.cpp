// SPDX-License-Identifier: BSD-2-Clause-Patent
// dizi: copied from the ruan port (https://github.com/F-e-n-y-x/UniXNU-iPadOS-on-Redmi-Pad-Pro-5G, unixnu-ruan/package, commit 72cc448);
// the only change is the ruan-metal=1 guard in ruan_gpu_publish_accelerator(), since dizi does not build the Adreno accelerator.
// ruan: the board half of the GopFramebuffer port (UniXNU drivers/GopFramebuffer NativeLegacyDisplay.cpp, iOS build).
// Trimmed from UniXNU-gts7xlwifi package/LegacyDisplayProbe.cpp (itself UniXNU-alioth/sheng's): the display path only.
// Removed: touch, USB debug console, screenshot provider, GPU hand-off presenter, HID publisher, key store (ruan starts it
// from patches/xnu/ruan-keystore-probe.patch), CPU frequency, backlight, buttons and every T970 peripheral; the
// /chosen display-scale is static in board.toml instead of offline-legacy-unit-scale.
// What is left:
//   - native_legacy_display_probe(): registers the class (bsd_init, offline-legacy-register=1) and keeps the instance
//     until bsd_autoconf has published IOBSD.
//   - native_legacy_display_late_probe(): binds it to the firmware framebuffer through a NativeGOPFramebuffer nub under
//     /arm-io (phase 4) once IOKitBSDInit() returned.
//   - the *_observed hooks NativeLegacyDisplay.cpp imports: counters and optional panel bands only.
//   - the link stubs a static kernel link needs for the driver's weak imports (no Adreno, no NativeUfs DPU window here).
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOUserClient.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSSerialize.h>
#include <libkern/c++/OSData.h>
#include <kern/task.h>
#include <kern/thread_call.h>
#include <sys/proc.h>
#include <sys/proc_internal.h>
#include <pexpert/pexpert.h>
#include <console/video_console.h>
#include <mach/kmod.h>
#include <machine/machine_routines.h>

extern "C" struct vc_info vinfo;
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" void native_legacy_display_static_init(void) __asm__("__GLOBAL__sub_I_NativeLegacyDisplay.cpp");
extern "C" IOService *native_legacy_display_allocate(void);
extern "C" kern_return_t OSKextLoadKextWithIdentifier(const char *identifier);

static IOService *pendingLegacyDisplay;

// Everything NativeLegacyDisplay.cpp calls is declared extern "C" there, so this block stays open to the end of the file.
extern "C" {
volatile uint32_t native_legacy_stage;
volatile int native_legacy_meta_status = -1;
volatile uint32_t native_legacy_init_result, native_legacy_start_result, native_legacy_probe_match;
volatile uint32_t native_legacy_dt_attached, native_legacy_released;
volatile uint64_t native_legacy_object, native_legacy_video_base;
volatile int native_legacy_surface_status = -1;
volatile uint32_t native_legacy_surface_found;
volatile uint32_t native_legacy_pm_stage, native_legacy_pm_calls;
volatile int native_legacy_pm_status = -1;
volatile uint32_t native_legacy_swap_accepted_count, native_legacy_swap_rejected_count, native_legacy_swap_validation_reason;
volatile uint64_t native_legacy_rej_surface[7];
volatile uint32_t native_legacy_frame_count, native_legacy_transfer_calls, native_legacy_registration_calls;
volatile int native_legacy_transfer_status = -1;
volatile uint64_t native_legacy_transfer_bytes, native_legacy_copy_n, native_legacy_copy_last, native_legacy_copy_max;
volatile uint32_t native_legacy_client_calls, native_legacy_retirement_calls, native_legacy_gpu_fallbacks;
volatile int native_legacy_client_pid, native_legacy_client_status = -1;
volatile uint64_t native_legacy_gop_physical, native_legacy_gop_bytes;
volatile uint64_t native_legacy_gop_virtual;   // the scanout mapping: package/UsbDebugCdc.cpp screen.snapshot reads it
volatile uint32_t native_legacy_gop_width, native_legacy_gop_height;
volatile uint64_t native_legacy_vsync_events[6];

// ---- link stubs: the driver imports these weak, and a static kernel link still needs a definition ----
// No Adreno driver on ruan: no fence to wait for, so direct display declines and the CPU copy stays.
__attribute__((weak)) bool native_adreno_fences(uint32_t *, uint32_t *) { return false; }
__attribute__((weak)) bool native_adreno_fences_detail(uint32_t *, uint32_t *, uint32_t *) { return false; }
// No GPU trace ring (GopFramebuffer NativeGpuTrace.h, gpu-trace=1 needs the Adreno driver): tracing reports off.
__attribute__((weak)) int native_gpu_trace_enabled(void) { return 0; }
__attribute__((weak)) void native_gpu_trace_record(uint32_t, uint32_t, const uint64_t *, uint32_t) {}
// No NativeUfs DPU window (dpu-scanout stays 0): a zero state and a mapper that maps nothing decline direct scanout.
__attribute__((weak)) volatile uint32_t native_ufs_dpu_state;
__attribute__((weak)) uint32_t native_ufs_dpu_map(unsigned, const uint64_t *, unsigned) { return 0; }

// The compositor's IOSurface stride field can hold pixels while the driver compares it with width*4 (UniXNU-alioth
// LinkStubs.c): take it as pixels when the allocation and the row count prove it. The raw getter is bound by
// build-gop-legacy-display.py to the original IOSurface accessor.
uint64_t native_legacy_surface_stride_raw(OSObject *);
uint64_t native_legacy_surface_allocation(OSObject *);
uint64_t native_legacy_surface_height(OSObject *);
uint64_t native_legacy_surface_stride(OSObject *surface) {
	uint64_t stride = native_legacy_surface_stride_raw(surface);
	uint64_t allocation = native_legacy_surface_allocation(surface), height = native_legacy_surface_height(surface);
	return stride && allocation && height && stride <= allocation / height / 4 ? stride * 4 : stride;
}

// ---- scanout arbitration with the boot-progress page (package/BootProgress.c) ----
// Weak: BootProgress.c's strong definition wins when it is linked (it yields the panel for good); without it, always go.
__attribute__((weak)) int boot_progress_prepare_scanout(void) { return 1; }
__attribute__((weak)) void boot_progress_cancel_scanout(void) {}

static volatile unsigned native_legacy_prepare_failures;
bool native_legacy_prepare_scanout(void) {
	if (ml_at_interrupt_context() || !ml_get_interrupts_enabled()) {
		return false;
	}
	for (unsigned attempt = 0; attempt < 2000; ++attempt) {  // up to ~2 s: a boot-page draw in progress finishes first
		if (boot_progress_prepare_scanout()) {
			return true;
		}
		IOSleep(1);
	}
	native_legacy_prepare_failures = native_legacy_prepare_failures + 1;
	boot_progress_cancel_scanout();
	return false;
}

// ---- panel bands (offline-legacy-reached=1 only): 7 grey service registered, 8 violet a swap arrived, 9 white a
// frame was copied into the scanout. One photo then tells "no client" from "client, frames refused" from "frames copied".
// Each band is painted once: the next frame copy covers it, so the bands never stay over the UI (gts7xlwifi v23).
static void native_legacy_paint_band(unsigned index, uint32_t colour) {
	static volatile uint32_t painted;
	unsigned enabled = 0;
	if (!PE_parse_boot_argn("offline-legacy-reached", &enabled, sizeof(enabled)) || !enabled ||
	    (__atomic_fetch_or(&painted, 1u << index, __ATOMIC_RELAXED) & (1u << index))) {
		return;
	}
	uint64_t base = vinfo.v_baseaddr;
	uint32_t rowbytes = vinfo.v_rowbytes, width = vinfo.v_width, height = vinfo.v_height;
	if (!base || vinfo.v_depth != 32 || !width || !height || rowbytes < width * 4u) {
		return;
	}
	for (uint64_t row = height * index / 16u; row < height * (index + 1u) / 16u; row++) {
		volatile uint32_t *line = (volatile uint32_t *)((volatile uint8_t *)base + row * rowbytes);
		for (uint32_t column = 0; column < width; column++) {
			line[column] = colour;
		}
	}
	__asm__ volatile("dsb sy" ::: "memory");
}

// ---- observation hooks the driver imports (counters only; nothing here changes a verdict) ----
__attribute__((noinline)) void native_legacy_display_checkpoint(void) { __asm__ volatile("" ::: "memory"); }

void native_legacy_pm_observed(unsigned stage, IOReturn status, unsigned long) {
	native_legacy_pm_stage = stage;
	native_legacy_pm_status = status;
	native_legacy_pm_calls = native_legacy_pm_calls + 1;
}

void native_legacy_surface_rejected(uint64_t width, uint64_t height, uint32_t format, uint32_t planes,
    uint64_t stride, uint64_t allocation, uint64_t bytes) {
	const uint64_t v[7] = {width, height, format, planes, stride, allocation, bytes};
	for (unsigned i = 0; i < 7; ++i) {
		native_legacy_rej_surface[i] = v[i];
	}
}

void native_legacy_frame_observed(unsigned, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t) {
	native_legacy_frame_count = native_legacy_frame_count + 1;
}
void native_legacy_frame_colors_observed(const uint32_t *, const uint64_t *, uint64_t) {}
void native_legacy_swap_stage(unsigned) {}

void native_legacy_swap_validation_observed(bool accepted, unsigned reason, const void *, const void *) {
	native_legacy_paint_band(8, 0xFF8000FFu);
	if (accepted) {
		native_legacy_swap_accepted_count = native_legacy_swap_accepted_count + 1;
	} else {
		native_legacy_swap_rejected_count = native_legacy_swap_rejected_count + 1;
		native_legacy_swap_validation_reason = reason;
	}
}

void native_legacy_copy_timing_observed(uint64_t ticks, uint64_t) {
	native_legacy_copy_n = native_legacy_copy_n + 1;
	native_legacy_copy_last = ticks;
	if (ticks > native_legacy_copy_max) {
		native_legacy_copy_max = ticks;
	}
}

void native_legacy_transfer_observed(IOReturn status, const void *, uint64_t bytes) {
	native_legacy_transfer_calls = native_legacy_transfer_calls + 1;
	native_legacy_transfer_status = status;
	native_legacy_transfer_bytes = bytes;
	if (status == kIOReturnSuccess) {
		native_legacy_paint_band(9, 0xFFFFFFFFu);
	}
}

extern int ruan_gpu_is_s5_ready(void) __attribute__((weak_import));
extern int ruan_gpu_run(unsigned mode, int (*trace)(void *, const char *), void *ctx) __attribute__((weak_import));
extern int ruan_gpu_stream0_map_page(uint32_t va_addr, uint64_t pa_addr, uint32_t bytes) __attribute__((weak_import));
extern void ruan_gpu_stream0_tlb_flush(void) __attribute__((weak_import));
extern int ruan_gpu_dma_blit_frame(uint32_t src_va, uint32_t dst_va, uint32_t total_dwords) __attribute__((weak_import));
extern void native_legacy_gpu_complete(void *display, int status);

volatile uint64_t native_legacy_gpu_blits = 0;
volatile uint32_t native_legacy_gpu_last_ticks = 0;
volatile int native_legacy_gpu_last_fallback_reason = 0;
void native_legacy_gpu_fallback_observed(int status);

static thread_call_t s_gpu_complete_call = NULL;

static void deferred_gpu_complete(thread_call_param_t p0, thread_call_param_t p1)
{
	(void)p1;
	native_legacy_gpu_complete((void *)p0, 0);
}

// Track up to 4 compositor surfaces to avoid remapping and rebinding across frames
struct GpuSlot {
	IOMemoryDescriptor *descriptor;
	IOMemoryMap *map;
	uint32_t gpu_va;
	uint64_t last_cycle;
};
static GpuSlot s_gpu_slots[4] = {};
static uint64_t s_gpu_cycle = 0;
static thread_call_t s_gpu_stream_call = NULL;
static volatile uint32_t s_gpu_streaming_active = 0;
static volatile uint32_t s_gpu_blit_lock = 0;

static void gpu_stream_tick(thread_call_param_t p0, thread_call_param_t p1)
{
	(void)p0; (void)p1;
	if (s_gpu_streaming_active) {
		if (OSCompareAndSwap(0, 1, (UInt32 *)&s_gpu_blit_lock)) {
			if (s_gpu_slots[0].descriptor && s_gpu_slots[0].gpu_va) {
				uint64_t t0, t1;
				__asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(t0));
				int rc = ruan_gpu_dma_blit_frame(s_gpu_slots[0].gpu_va, 0x50000000u, 1600 * 2560);
				__asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(t1));
				if (rc == 0) {
					native_legacy_gpu_blits = native_legacy_gpu_blits + 1;
					native_legacy_gpu_last_ticks = (uint32_t)(t1 - t0);
				}
			}
			s_gpu_blit_lock = 0;
		}
		if (s_gpu_streaming_active && s_gpu_stream_call) {
			uint64_t deadline;
			clock_interval_to_deadline(500, NSEC_PER_MSEC, &deadline);
			thread_call_enter_delayed(s_gpu_stream_call, deadline);
		}
	}
}

// Adreno 710 Stage S5 Mode 16 In-Kernel Display Frame Blitter Hook (fb-gpu-stream=1 or fb-gpu=1)
// Dispatches compositor surfaces directly to the Adreno 710 hardware blitter via CP_MEMCPY
// and monotonic fences, eliminating CPU frame presentation overhead.
bool native_legacy_gpu_offer(void *display, IOMemoryDescriptor *memory, uint64_t sourceStride, uint32_t width, uint32_t height, uint32_t format)
{
	unsigned fb_gpu_stream = 0, fb_gpu = 0;
	PE_parse_boot_argn("fb-gpu-stream", &fb_gpu_stream, sizeof(fb_gpu_stream));
	PE_parse_boot_argn("fb-gpu", &fb_gpu, sizeof(fb_gpu));
	if (fb_gpu_stream != 1 && fb_gpu != 1) {
		native_legacy_gpu_fallback_observed(-1);
		return false;
	}
	if (!&ruan_gpu_is_s5_ready || !ruan_gpu_is_s5_ready()) {
		if (&ruan_gpu_run) {
			ruan_gpu_run(16, NULL, NULL);
		}
		if (!&ruan_gpu_is_s5_ready || !ruan_gpu_is_s5_ready()) {
			IOLog("ruan-gpu-offer: S5 not ready\n");
			native_legacy_gpu_fallback_observed(-2);
			return false;
		}
	}
	if (!&ruan_gpu_dma_blit_frame || !&ruan_gpu_stream0_map_page || !&ruan_gpu_stream0_tlb_flush) {
		IOLog("ruan-gpu-offer: weak symbols missing\n");
		native_legacy_gpu_fallback_observed(-3);
		return false;
	}
	if (!memory || !display || width != 1600 || height != 2560) {
		IOLog("ruan-gpu-offer: invalid params mem=%p disp=%p %ux%u\n", memory, display, width, height);
		native_legacy_gpu_fallback_observed(-4);
		return false;
	}
	if (format != 1 && format != 0 && format != 0x26424741 && format != 0x42475241) {
		IOLog("ruan-gpu-offer: unsupported format 0x%x\n", format);
		native_legacy_gpu_fallback_observed(-5);
		return false;
	}
	if (sourceStride != (uint64_t)width * 4u) {
		IOLog("ruan-gpu-offer: stride mismatch: stride=%llu expected=%llu fmt=0x%x\n",
		      (unsigned long long)sourceStride, (unsigned long long)width * 4u, format);
		native_legacy_gpu_fallback_observed(-6);
		return false;
	}

	s_gpu_cycle++;

	int slot_idx = -1;
	for (int i = 0; i < 4; i++) {
		if (s_gpu_slots[i].descriptor == memory) {
			slot_idx = i;
			break;
		}
	}

	uint32_t src_gpu_va = 0;
	if (slot_idx >= 0) {
		src_gpu_va = s_gpu_slots[slot_idx].gpu_va;
		s_gpu_slots[slot_idx].last_cycle = s_gpu_cycle;
	} else {
		// Pick LRU or empty slot
		int pick = 0;
		uint64_t oldest = s_gpu_slots[0].last_cycle;
		for (int i = 0; i < 4; i++) {
			if (!s_gpu_slots[i].descriptor) { pick = i; break; }
			if (s_gpu_slots[i].last_cycle < oldest) { oldest = s_gpu_slots[i].last_cycle; pick = i; }
		}
		slot_idx = pick;
		if (s_gpu_slots[slot_idx].map) {
			s_gpu_slots[slot_idx].map->release();
			s_gpu_slots[slot_idx].map = nullptr;
		}
		if (s_gpu_slots[slot_idx].descriptor) {
			s_gpu_slots[slot_idx].descriptor->complete();
			s_gpu_slots[slot_idx].descriptor->release();
			s_gpu_slots[slot_idx].descriptor = nullptr;
		}

		src_gpu_va = 0x60000000u + (uint32_t)slot_idx * 0x01000000u;

		// Map physical pages of memory to src_gpu_va and retain wire
		bool ok = true;
		if (memory->prepare() == kIOReturnSuccess) {
			for (IOByteCount offset = 0; offset < memory->getLength() && ok;) {
				IOByteCount segLen = 0;
				addr64_t pa = memory->getPhysicalSegment(offset, &segLen, kIOMemoryMapperNone);
				if (!pa || !segLen) { ok = false; break; }
				if (ruan_gpu_stream0_map_page(src_gpu_va + (uint32_t)offset, pa, (uint32_t)segLen) != 0) {
					ok = false;
					break;
				}
				offset += segLen;
			}
		} else {
			ok = false;
		}
		if (!ok) {
			if (memory) memory->complete();
			IOLog("ruan-gpu-offer: mapping failed for slot %d\n", slot_idx);
			native_legacy_gpu_fallback_observed(-7);
			return false;
		}
		ruan_gpu_stream0_tlb_flush();
		memory->retain();
		s_gpu_slots[slot_idx].descriptor = memory;
		s_gpu_slots[slot_idx].map = memory->map(kIOMapAnywhere | kIOMapReadOnly | kIOMapCopybackCache);
		s_gpu_slots[slot_idx].gpu_va = src_gpu_va;
		s_gpu_slots[slot_idx].last_cycle = s_gpu_cycle;
	}

	// Flush CPU cache of the source memory so physical DRAM has latest pixels
	if (s_gpu_slots[slot_idx].map && s_gpu_slots[slot_idx].map->getVirtualAddress()) {
		flush_dcache64((addr64_t)s_gpu_slots[slot_idx].map->getVirtualAddress(), (unsigned)s_gpu_slots[slot_idx].map->getLength(), false);
	}

	// Execute GPU DMA blit to GOP Framebuffer (0x50000000 -> phys 0xb8000000) under blit lock
	while (!OSCompareAndSwap(0, 1, (UInt32 *)&s_gpu_blit_lock)) {
		delay(10);
	}
	uint64_t t0;
	__asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(t0));
	int rc = ruan_gpu_dma_blit_frame(src_gpu_va, 0x50000000u, width * height);
	uint64_t t1;
	__asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(t1));
	s_gpu_blit_lock = 0;

	if (rc != 0) {
		IOLog("ruan-gpu-offer: blit failed rc=%d\n", rc);
		native_legacy_gpu_fallback_observed(rc);
		return false;
	}

	native_legacy_gpu_blits = native_legacy_gpu_blits + 1;
	native_legacy_gpu_last_ticks = (uint32_t)(t1 - t0);

	// Start continuous background streaming timer if fb-gpu-stream=1 is enabled
	if (fb_gpu_stream == 1 && !s_gpu_streaming_active) {
		s_gpu_streaming_active = 1;
		if (!s_gpu_stream_call) {
			s_gpu_stream_call = thread_call_allocate(gpu_stream_tick, NULL);
		}
		if (s_gpu_stream_call) {
			uint64_t deadline;
			clock_interval_to_deadline(500, NSEC_PER_MSEC, &deadline);
			thread_call_enter_delayed(s_gpu_stream_call, deadline);
		}
	}

	// Queue asynchronous completion to run after NativeLegacyDisplay unlocks its workloop gate
	if (!s_gpu_complete_call) {
		s_gpu_complete_call = thread_call_allocate(deferred_gpu_complete, NULL);
	}
	if (s_gpu_complete_call) {
		thread_call_enter1(s_gpu_complete_call, (thread_call_param_t)display);
	}
	return true;
}
// Native Adreno GPU Accelerator Publication (IOAcceleratorES -> Metal discovery)
extern "C" void native_adreno_accelerator_static_init(void) __asm__("__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp") __attribute__((weak_import));
extern "C" IOService *native_adreno_accelerator_allocate(void) __attribute__((weak_import));
extern "C" unsigned native_adreno_accelerator_instance_size(void) __attribute__((weak_import));

volatile uint32_t ruan_metal_stage = 0;
volatile int ruan_metal_status = -1;
volatile uint32_t ruan_metal_registered = 0;
volatile uint32_t native_adreno_metal_opens = 0;
volatile uint32_t native_adreno_metal_property_reads = 0;
char native_adreno_last_property[64] = {};
char native_adreno_last_client[64] = {};
__attribute__((unused)) static IOService *s_accelerator = nullptr;

void native_adreno_note_property_read(const char *key) {
	native_adreno_metal_property_reads++;
	if (key) {
		strlcpy(native_adreno_last_property, key, sizeof(native_adreno_last_property));
	}
}

extern "C" IOUserClient *native_adreno_user_client_create(task_t, void *, UInt32, OSDictionary *) __attribute__((weak_import));

IOReturn native_adreno_new_user_client(IOService *provider, task_t owningTask, void *securityID,
                                       UInt32 type, OSDictionary *properties, IOUserClient **handler,
                                       unsigned limit) {
	(void)securityID; (void)limit;
	if (handler) *handler = nullptr;
	native_adreno_metal_opens++;
	if (owningTask) {
		proc_t p = (proc_t)get_bsdtask_info(owningTask);
		if (p) proc_name(proc_pid(p), native_adreno_last_client, sizeof(native_adreno_last_client));
	}
	if (!handler || !&native_adreno_user_client_create) return kIOReturnUnsupported;
	IOUserClient *client = native_adreno_user_client_create(owningTask, securityID, type, properties);
	if (!client) return kIOReturnNoMemory;
	if (provider && !client->attach(provider)) {
		client->release();
		return kIOReturnNotAttached;
	}
	if (provider && !client->start(provider)) {
		client->detach(provider);
		client->release();
		return kIOReturnError;
	}
	*handler = client;
	return kIOReturnSuccess;
}

void ruan_gpu_publish_accelerator(void) {
	/* dizi: the Adreno accelerator is not built (package/BootProgressRuanStubs.c only stands in for its symbols), so the
	 * publication runs only when explicitly asked with ruan-metal=1. */
	{
		uint32_t metal = 0;
		if (!PE_parse_boot_argn("ruan-metal", &metal, sizeof(metal)) || !metal) {
			ruan_metal_stage = 0;
			ruan_metal_status = kIOReturnUnsupported;
			return;
		}
	}
	if (!&native_adreno_accelerator_static_init || !&native_adreno_accelerator_allocate || !&native_adreno_accelerator_instance_size) {
		ruan_metal_stage = 0;
		ruan_metal_status = kIOReturnUnsupported;
		return;
	}
	ruan_metal_stage = 1;
	int kext_status = OSKextLoadKextWithIdentifier("com.apple.iokit.IOGPUFamily");
	if (kext_status != kIOReturnSuccess && kext_status != kOSReturnSuccess) {
		ruan_metal_status = kext_status;
		return;
	}
	const OSSymbol *name = OSSymbol::withCString("IOAcceleratorES");
	const OSMetaClass *parent = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
	OSSafeReleaseNULL(name);
	if (!parent || parent->getClassSize() != 136) {
		ruan_metal_status = kIOReturnNotFound;
		return;
	}
	ruan_metal_stage = 2;
	void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
	if (!handle) {
		ruan_metal_status = kIOReturnNoResources;
		return;
	}
	native_adreno_accelerator_static_init();
	ruan_metal_status = OSMetaClass::postModLoad(handle);
	if (ruan_metal_status != kIOReturnSuccess && ruan_metal_status != kOSReturnSuccess) return;
	if (native_adreno_accelerator_instance_size() != 136) {
		ruan_metal_status = kIOReturnInvalid;
		return;
	}
	ruan_metal_stage = 3;
	IOService *accelerator = native_adreno_accelerator_allocate();
	if (!accelerator) {
		ruan_metal_status = kIOReturnNoMemory;
		return;
	}
	if (!accelerator->init()) {
		accelerator->release();
		ruan_metal_status = kIOReturnError;
		return;
	}
	accelerator->setProperty("MetalPluginName", "NativeAdrenoMetal");
	accelerator->setProperty("MetalPluginClassName", "NativeAdrenoMetalDevice");
	ruan_metal_stage = 4;
	if (!accelerator->attach(IOService::getPlatform())) {
		accelerator->release();
		ruan_metal_status = kIOReturnNotAttached;
		return;
	}
	accelerator->registerService();
	s_accelerator = accelerator;
	ruan_metal_registered = 1;
	ruan_metal_stage = 5;
	ruan_metal_status = kIOReturnSuccess;
}

void native_legacy_gpu_fallback_observed(int reason) {
	native_legacy_gpu_fallbacks = native_legacy_gpu_fallbacks + 1;
	native_legacy_gpu_last_fallback_reason = reason;
}
void native_legacy_retirement_observed(IOService *) { native_legacy_retirement_calls = native_legacy_retirement_calls + 1; }

void native_legacy_vsync_observed(unsigned event, unsigned) {
	if (event < 6) {
		native_legacy_vsync_events[event] = native_legacy_vsync_events[event] + 1;
	}
}

void native_legacy_registration_observed(IOService *) {
	native_legacy_registration_calls = native_legacy_registration_calls + 1;
	native_legacy_paint_band(7, 0xFF808080u);
}

void native_legacy_client_enter(task_t task, uint32_t) {
	native_legacy_client_calls = native_legacy_client_calls + 1;
	native_legacy_client_pid = task ? proc_pid((proc_t)get_bsdtask_info(task)) : 0;
}
void native_legacy_client_observed(IOReturn status, IOUserClient *) { native_legacy_client_status = status; }

bool native_legacy_gop_mapping_observed(IOService *object, IOMemoryMap *mapping, uint32_t width, uint32_t height) {
	if ((uintptr_t)object != native_legacy_object) {
		panic("NativeLegacyDisplay: wrong mapping owner");
	}
	native_legacy_gop_physical = mapping->getPhysicalAddress();
	native_legacy_gop_virtual = mapping->getVirtualAddress();
	native_legacy_gop_bytes = mapping->getLength();
	native_legacy_gop_width = width;
	native_legacy_gop_height = height;
	return true;
}

// A guarded backend leaf was reached: stop and name it, the panic screen is ruan's only log.
__attribute__((noreturn, noinline)) void native_legacy_backend_guard(unsigned slot, void *, void *caller) {
	// prep: hand-offs the boot page refused; copy NotReady with prep=0 means the console/surface check refused the frame.
	panic("NativeLegacyDisplay: leaf=%u caller=%llx stage=%u PM=%u swaps=%u/%u copy=%d bytes=%llu prep=%u calls=%u",
	    slot, (uint64_t)(uintptr_t)caller, native_legacy_stage, native_legacy_pm_stage, native_legacy_swap_accepted_count,
	    native_legacy_swap_rejected_count, native_legacy_transfer_status, native_legacy_transfer_bytes,
	    native_legacy_prepare_failures, native_legacy_transfer_calls);
}

// offline-legacy-verdict=1: a failed bring-up step panics with its name instead of leaving the boot page untouched.
__attribute__((noinline)) static void native_legacy_verdict(const char *where) {
	unsigned enabled = 0;
	if (PE_parse_boot_argn("offline-legacy-verdict", &enabled, sizeof(enabled)) && enabled) {
		panic("NativeLegacyDisplay: %s stage=%u meta=%d init=%u probe=%u start=%u dt=%u surface=%d/%u video=%llx",
		    where, native_legacy_stage, native_legacy_meta_status, native_legacy_init_result, native_legacy_probe_match,
		    native_legacy_start_result, native_legacy_dt_attached, native_legacy_surface_status, native_legacy_surface_found,
		    native_legacy_video_base);
	}
	native_legacy_display_checkpoint();
}

// The firmware console must be a plain 32-bit, unrotated, single-plane framebuffer (ruan: 1600x2560 BGRX at 0xB8000000).
static bool usable_console(PE_Video *video) {
	return !PE_current_console(video) && video->v_baseAddr && video->v_width && video->v_height && video->v_depth == 32 &&
	       !video->v_rotate && video->v_width <= 16384 && video->v_height <= 16384 &&
	       video->v_rowBytes >= video->v_width * 4 && video->v_rowBytes <= UINT64_MAX / video->v_height;
}

// bsd_init (offline-component-load-probes.patch), after IOMobileGraphicsFamily loaded, with offline-legacy-register=1.
void native_legacy_display_probe(void) {
	if (native_legacy_stage) {
		return;  // two call sites; the class registers once
	}
	native_legacy_stage = 1;
	void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
	if (!handle) {
		return native_legacy_verdict("preModLoad");
	}
	native_legacy_display_static_init();
	native_legacy_meta_status = OSMetaClass::postModLoad(handle);
	if (native_legacy_meta_status) {
		return native_legacy_verdict("postModLoad");
	}
	PE_Video video = {};
	native_legacy_stage = 2;
	if (!usable_console(&video)) {
		return native_legacy_verdict("console");
	}
	IOService *display = native_legacy_display_allocate();
	native_legacy_object = (uintptr_t)display;
	if (!display) {
		return native_legacy_verdict("allocate");
	}
	native_legacy_stage = 3;
	native_legacy_init_result = display->init();
	unsigned phase = 1;
	PE_parse_boot_argn("offline-legacy-phase", &phase, sizeof(phase));
	if (native_legacy_init_result && phase == 4) {
		pendingLegacyDisplay = display;  // IOSurface needs IOBSD, published later by bsd_autoconf
		return;
	}
	display->release();
	native_legacy_released = 1;
	native_legacy_verdict("init");
}

// bsd_autoconf (offline-legacy-start.patch), after IOKitBSDInit().
void native_legacy_display_late_probe(void) {
	IOService *display = pendingLegacyDisplay;
	if (!display) {
		return native_legacy_verdict("no-pending-instance");
	}
	pendingLegacyDisplay = nullptr;
	native_legacy_surface_status = OSKextLoadKextWithIdentifier("com.apple.iokit.IOSurface");
	OSDictionary *matching = IOService::nameMatching("IOCoreSurfaceRoot");
	IOService *surface = matching ? IOService::waitForMatchingService(matching, 5000000000ULL) : nullptr;
	native_legacy_surface_found = surface != nullptr;
	OSSafeReleaseNULL(surface);
	OSSafeReleaseNULL(matching);
	PE_Video video = {};
	if (native_legacy_surface_status || !native_legacy_surface_found || !usable_console(&video)) {
		display->release();
		native_legacy_released = 1;
		return native_legacy_verdict("late-surface-or-console");
	}
	native_legacy_video_base = video.v_baseAddr;
	// The real firmware framebuffer as the nub's only memory: no invented panel timing, compatible or register.
	native_legacy_stage = 4;
	IOPlatformDevice *nub = new IOPlatformDevice;
	IOService *parent = IOService::getResourceService();
	IODeviceMemory *memory = IODeviceMemory::withRange(video.v_baseAddr, video.v_rowBytes * video.v_height);
	OSArray *ranges = OSArray::withCapacity(1);
	IORegistryEntry *arm_io = IORegistryEntry::fromPath("/arm-io", gIODTPlane);
	bool nubAttached = false, nubStarted = false, attached = false, started = false;
	if (nub && memory && ranges && parent && arm_io && nub->init()) {
		ranges->setObject(memory);
		nub->setDeviceMemory(ranges);
		nub->setName("NativeGOPFramebuffer");
		nubAttached = nub->attach(parent);
		nubStarted = nubAttached && nub->start(parent);
		// Phase 4: a display-subsystem node under the ADT's /arm-io, where the system looks for the display.
		const char type[] = "display-subsystem";
		OSData *data = OSData::withBytes(type, sizeof(type));
		if (nubStarted && data && nub->setProperty("device_type", data)) {
			nub->setName("gop-display", gIODTPlane);
			native_legacy_dt_attached = nub->attachToParent(arm_io, gIODTPlane);
		}
		OSSafeReleaseNULL(data);
		SInt32 score = 0;
		native_legacy_probe_match = native_legacy_dt_attached && display->probe(nub, &score) == display;
		attached = native_legacy_probe_match && display->attach(nub);
		if (attached) {
			native_legacy_stage = 5;
			started = display->start(nub);
			native_legacy_start_result = started;
		}
	}
	if (started) {
		native_legacy_stage = 10;
		OSSafeReleaseNULL(arm_io);
		// Touch and buttons: the HID publisher (package/NativeHidInput.cpp + HidInputProbe.cpp, from UniXNU-j716f), started the
		// way j716f does it, once the display is up (offline-hid-input=1 offline-hid-home=1 sheng-touch-hid=1).
		extern void native_hid_input_probe(void);
		native_hid_input_probe();
		// Live USB terminal, screen capture and (opt-in) reboot to fastboot: package/UsbDebugCdc.cpp, off unless ruan-usbdbg=1.
		extern void native_usb_debug_probe(void);
		native_usb_debug_probe();
		// Display Backlight (AppleARMBacklight & IODisplayParameters): package/RuanBacklight.cpp
		extern bool ruan_backlight_start(void) __attribute__((weak_import));
		if (&ruan_backlight_start) ruan_backlight_start();
		// Qualcomm WCN6750 Wi-Fi: package/RuanWifiProbe.c
		extern void ruan_wifi_init(void) __attribute__((weak_import));
		if (&ruan_wifi_init) ruan_wifi_init();
		// Qualcomm LPASS Quad WSA883x Audio: package/RuanAudioProbe.c
		extern void ruan_audio_init(void) __attribute__((weak_import));
		if (&ruan_audio_init) ruan_audio_init();
		// Native Adreno GPU Accelerator Publication (IOAcceleratorES -> Metal discovery)
		ruan_gpu_publish_accelerator();
		return native_legacy_display_checkpoint();  // nub, memory and ranges stay owned by the registry
	}
	native_legacy_stage = 6;
	if (attached) display->detach(nub);
	if (native_legacy_dt_attached) nub->detachFromParent(arm_io, gIODTPlane);
	if (nubStarted) nub->stop(parent);
	if (nubAttached) nub->detach(parent);
	OSSafeReleaseNULL(ranges);
	OSSafeReleaseNULL(memory);
	OSSafeReleaseNULL(nub);
	OSSafeReleaseNULL(arm_io);
	display->release();
	native_legacy_released = 1;
	native_legacy_verdict(native_legacy_probe_match ? "attach-or-start" : nubStarted ? "probe" : "nub");
}
}

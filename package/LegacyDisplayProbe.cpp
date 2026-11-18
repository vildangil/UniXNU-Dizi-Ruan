// SPDX-License-Identifier: BSD-2-Clause-Patent
// dizi: copied unchanged from the ruan port (https://github.com/F-e-n-y-x/UniXNU-iPadOS-on-Redmi-Pad-Pro-5G, unixnu-ruan/package, commit 5ce47b1); ruan and dizi share the SoC, panel size and iPadOS build.
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

// No GPU on ruan (Adreno 710 has no driver): every frame takes the CPU copy.
bool native_legacy_gpu_offer(void *, IOMemoryDescriptor *, uint64_t, uint32_t, uint32_t, uint32_t) { return false; }
void native_legacy_gpu_fallback_observed(int) { native_legacy_gpu_fallbacks = native_legacy_gpu_fallbacks + 1; }
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

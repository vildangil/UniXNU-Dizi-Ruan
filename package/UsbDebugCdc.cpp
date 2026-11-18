// SPDX-License-Identifier: BSD-2-Clause-Patent
// Live USB CDC-ACM diagnostic terminal, ramoops streamer, GSC1 framebuffer capture and (opt-in) reboot to fastboot for the
// Redmi Pad Pro 5G (ruan, SM7435). Ported from UniXNU-j716f package/UsbDebugCdc.cpp (TB-J716F, SM8250, verified there
// 2026-11-05) by usb-dev/tools/port-from-j716f.py. Off unless ruan-usbdbg=1; reboot.fastboot also needs ruan-usbdbg-reboot=1.

#include "UsbDebugCdc.h"
#include "UsbDebugWire.h"

#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <string.h>
#include <libkern/c++/OSSharedPtr.h>
#include <kern/task.h>
#include <kern/thread.h>
#include <sys/param.h>
#include <sys/errno.h>
#include <sys/fcntl.h>
#include <sys/vnode.h>
#include <sys/uio.h>
#include <sys/dirent.h>
#include <sys/msgbuf.h>
#include <pexpert/pexpert.h>

#include "RuanBacklight.h"   // SY7758 backlight (weak: the command says so when the driver is not linked)
extern "C" int ruan_backlight_set_level(uint32_t level) __attribute__((weak_import));
extern "C" int ruan_backlight_reg(uint8_t reg, int value) __attribute__((weak_import));
extern "C" struct ruan_backlight_state g_ruan_backlight __attribute__((weak_import));

extern "C" {
#include "SmmuBypass.h"
#include "RuanBattery.h"

extern struct hakios_battery_state g_ruan_battery __attribute__((weak_import));
extern void boot_progress_stage(const char *text) __attribute__((weak_import));

// package/LegacyDisplayProbe.cpp (ruan): the GOP scanout NativeLegacyDisplay copies frames into.
extern volatile uint64_t native_legacy_gop_virtual __attribute__((weak_import));
extern volatile uint64_t native_legacy_gop_physical __attribute__((weak_import));
extern volatile uint64_t native_legacy_gop_bytes __attribute__((weak_import));
extern volatile uint32_t native_legacy_gop_width __attribute__((weak_import));
extern volatile uint32_t native_legacy_gop_height __attribute__((weak_import));
extern volatile uint32_t native_legacy_stage __attribute__((weak_import));
extern volatile uint64_t native_legacy_copy_n __attribute__((weak_import));
extern volatile uint64_t native_legacy_gpu_blits __attribute__((weak_import));
extern volatile uint32_t native_legacy_gpu_last_ticks __attribute__((weak_import));

extern volatile uint32_t ruan_metal_stage __attribute__((weak_import));
extern volatile int ruan_metal_status __attribute__((weak_import));
extern volatile uint32_t ruan_metal_registered __attribute__((weak_import));
extern volatile uint32_t native_adreno_metal_opens __attribute__((weak_import));
extern volatile uint32_t native_adreno_metal_property_reads __attribute__((weak_import));
extern char native_adreno_last_property[64] __attribute__((weak_import));
extern char native_adreno_last_client[64] __attribute__((weak_import));

extern volatile uint32_t native_legacy_swap_accepted_count __attribute__((weak_import));
extern volatile uint32_t native_legacy_swap_rejected_count __attribute__((weak_import));
extern volatile uint32_t native_legacy_early_retires __attribute__((weak_import));
extern volatile uint32_t native_legacy_gpu_fallbacks __attribute__((weak_import));
extern volatile int native_legacy_gpu_last_fallback_reason __attribute__((weak_import));
extern "C" uint32_t ruan_gpu_ring_wraps(void) __attribute__((weak_import));
extern "C" int ruan_gpu_dma_blit_frame(uint32_t, uint32_t, uint32_t) __attribute__((weak_import));
extern "C" int native_adreno_fences(uint32_t *, uint32_t *) __attribute__((weak_import));
extern volatile uint64_t native_legacy_vsync_events[6] __attribute__((weak_import));

// package/RuanInput.c (touch + buttons)
extern volatile uint32_t ruan_touch_events __attribute__((weak_import));
extern volatile uint32_t ruan_button_events __attribute__((weak_import));
extern char ruan_input_row[96] __attribute__((weak_import));
extern "C" void hakios_touch_post(uint32_t, uint32_t, uint32_t, uint32_t) __attribute__((weak_import));

// package/BootReset.c: probe the PMIC reboot-reason cell; write "bootloader" into it and read it back.
extern int boot_reset_probe(char *text, unsigned cap) __attribute__((weak_import));
extern int boot_reset_mark_bootloader(char *text, unsigned cap) __attribute__((weak_import));
extern struct msgbuf *msgbufp;   // bsd/kern/subr_log.c (XNU_KERNEL_PRIVATE in sys/msgbuf.h)
extern const char *ruan_wifi_status_str(void) __attribute__((weak_import));
extern const char *ruan_audio_status_str(void) __attribute__((weak_import));

// The boot-progress banner prints this (package/BootProgress.c defines it weak; this definition wins when linked).
char ruan_usb_short[48] = "usb: off";
}

struct UsbPlaceTag {};
inline void *operator new(size_t, void *p, UsbPlaceTag) noexcept { return p; }

namespace {

#include "UsbDebugCommands.h"
#include "UsbDebugFiles.h"
#include "UsbDebugHw.h"

static const char *const kUsbStrings[4] = {
    "",
    "UniXNU",
    "Redmi Pad Pro 5G Debug CDC",
    "RUANDBG01"
};

static uint64_t nowMs() {
    uint64_t cnt = 0, frq = 0;
    __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(cnt) :: "memory");
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frq));
    return frq ? (cnt * 1000ULL) / frq : 0ULL;
}

static char gUsbHudLine0[112] = "usb: init";
static char gUsbHudLine1[112] = "reg: waiting...";

// ruan: no HUD is drawn into the scanout (the boot-progress banner owns it); the status lines go to "usb"/"status".
static void renderHudOverlay() {}

static void logStage(const char *msg) {
    if (msg) {
        strlcpy(gUsbHudLine0, msg, sizeof(gUsbHudLine0));
        strlcpy(ruan_usb_short, msg, sizeof(ruan_usb_short));
    }
    if (&boot_progress_stage && boot_progress_stage) {
        boot_progress_stage(msg);
    }
}

static int epCmd(UsbHw &hw, unsigned dep, uint32_t cmd, uint32_t p0, uint32_t p1, uint32_t p2, uint32_t *rawOut = nullptr) {
    const uint32_t cfg = hw.rd(DWC3_GUSB2PHYCFG(0));
    const uint32_t drop = cfg & (DWC3_GUSB2PHYCFG_SUSPHY | DWC3_GUSB2PHYCFG_ENBLSLPM);
    if (drop) hw.wr(DWC3_GUSB2PHYCFG(0), cfg & ~drop);
    hw.wr(DWC3_DEPCMDPAR0(dep), p0);
    hw.wr(DWC3_DEPCMDPAR1(dep), p1);
    hw.wr(DWC3_DEPCMDPAR2(dep), p2);
    hw.wr(DWC3_DEPCMD(dep), cmd | DWC3_DEPCMD_CMDACT);
    int st = -1;
    for (unsigned i = 0; i < 20000; ++i) {
        const uint32_t v = hw.rd(DWC3_DEPCMD(dep));
        if (!(v & DWC3_DEPCMD_CMDACT)) {
            if (rawOut) *rawOut = v;
            st = static_cast<int>(DWC3_DEPCMD_STATUS(v));
            break;
        }
        IODelay(1);
    }
    if (drop) hw.wr(DWC3_GUSB2PHYCFG(0), cfg);
    hw.lastCmdSt = st;
    return st;
}

static void endDepTransfer(UsbHw &hw, unsigned dep, uint32_t &rscIdx, bool &busyFlag) {
    if (rscIdx != 0u) {
        (void)epCmd(hw, dep,
                    DWC3_DEPCMD_ENDTRANSFER | DWC3_DEPCMD_HIPRI_FORCERM |
                    DWC3_DEPCMD_CMDIOC | DWC3_DEPCMD_PARAM(rscIdx),
                    0, 0, 0);
        IODelay(100);
        rscIdx = 0u;
    }
    busyFlag = false;
}

static volatile uint32_t *ep0TrbPtr(UsbHw &hw, unsigned slot = 0) {
    return reinterpret_cast<volatile uint32_t *>(hw.dmaVirt + DMA_EP0_TRB_OFF + slot * 16u);
}

static void ep0SetTrb(UsbHw &hw, unsigned slot, uint64_t pa, uint32_t sz, uint32_t type, bool last) {
    volatile uint32_t *t = ep0TrbPtr(hw, slot);
    t[0] = static_cast<uint32_t>(pa);
    t[1] = static_cast<uint32_t>(pa >> 32);
    t[2] = sz;
    t[3] = type | DWC3_TRB_CTRL_ISP_IMI | (last ? (DWC3_TRB_CTRL_IOC | DWC3_TRB_CTRL_LST) : DWC3_TRB_CTRL_CHN);
}

static void ep0CommitHead(UsbHw &hw) {
    __asm__ volatile("dsb sy" ::: "memory");
    volatile uint32_t *t = ep0TrbPtr(hw, 0);
    t[3] = t[3] | DWC3_TRB_CTRL_HWO;
    usbCacheRange(hw.dmaVirt + DMA_EP0_TRB_OFF, 64u, 1);
}

static void ep0Start(UsbHw &hw, unsigned dep) {
    const uint64_t pa = hw.dmaPhys + DMA_EP0_TRB_OFF;
    (void)epCmd(hw, dep, DWC3_DEPCMD_STARTTRANSFER, static_cast<uint32_t>(pa >> 32), static_cast<uint32_t>(pa), 0);
}

static void ep0ArmSetup(UsbHw &hw) {
    hw.ep0Stage = 0;
    hw.ep0Armed = 0;
    hw.ep0Trbs  = 1;
    usbCacheRange(hw.dmaVirt + DMA_EP0_BUF_OFF, 64u, 1);
    ep0SetTrb(hw, 0, hw.dmaPhys + DMA_EP0_BUF_OFF, 8u, DWC3_TRBCTL_CONTROL_SETUP, true);
    ep0CommitHead(hw);
    ep0Start(hw, 0);
}

static void ep0Restart(UsbHw &hw) {
    (void)epCmd(hw, 0, DWC3_DEPCMD_SETSTALL, 0, 0, 0);
    (void)epCmd(hw, 0, DWC3_DEPCMD_CLEARSTALL, 0, 0, 0);
    ep0ArmSetup(hw);
}

static void ep0StartData(UsbHw &hw, unsigned dep, uint32_t len) {
    hw.ep0Stage = 1;
    hw.ep0Armed = len;
    const uint64_t bufPa = hw.dmaPhys + DMA_EP0_BUF_OFF;
    if (dep == 1u) {
        usbCacheRange(hw.dmaVirt + DMA_EP0_BUF_OFF, len ? len : 64u, 0);
        if (hw.ep0Zlp) {
            hw.ep0Zlp  = false;
            hw.ep0Trbs = 2;
            ep0SetTrb(hw, 1, bufPa, 0u, DWC3_TRBCTL_CONTROL_DATA, true);
            ep0TrbPtr(hw, 1)[3] |= DWC3_TRB_CTRL_HWO;
            __asm__ volatile("dsb sy" ::: "memory");
            ep0SetTrb(hw, 0, bufPa, len, DWC3_TRBCTL_CONTROL_DATA, false);
        } else {
            hw.ep0Trbs = 1;
            ep0SetTrb(hw, 0, bufPa, len, DWC3_TRBCTL_CONTROL_DATA, true);
        }
    } else {
        usbCacheRange(hw.dmaVirt + DMA_EP0_BUF_OFF, 64u, 1);
        hw.ep0Trbs = 1;
        // Synopsys DWC3 Databook 8.2.2: EP0 Control-Data OUT TRB size must be aligned to MaxPacketSize (64B)
        ep0SetTrb(hw, 0, bufPa, 64u, DWC3_TRBCTL_CONTROL_DATA, true);
    }
    ep0CommitHead(hw);
    ep0Start(hw, dep);
}

static void ep0StartStatus(UsbHw &hw, unsigned dep) {
    hw.ep0Stage = 3;
    hw.ep0Trbs  = 1;
    ep0SetTrb(hw, 0, hw.dmaPhys + DMA_EP0_BUF_OFF, 0u,
              hw.ep0Three ? DWC3_TRBCTL_CONTROL_STATUS3 : DWC3_TRBCTL_CONTROL_STATUS2, true);
    ep0CommitHead(hw);
    ep0Start(hw, dep);
}

static void armBulkOut(UsbHw &hw) {
    if (!hw.configured || hw.ep2Armed) return;
    usbCacheRange(hw.dmaVirt + DMA_EP2_BUF_OFF, hw.bulkMps, 1);
    volatile uint32_t *t = reinterpret_cast<volatile uint32_t *>(hw.dmaVirt + DMA_EP2_TRB_OFF);
    const uint64_t bufPa = hw.dmaPhys + DMA_EP2_BUF_OFF;
    const uint64_t trbPa = hw.dmaPhys + DMA_EP2_TRB_OFF;
    t[0] = static_cast<uint32_t>(bufPa);
    t[1] = static_cast<uint32_t>(bufPa >> 32);
    t[2] = hw.bulkMps;
    t[3] = DWC3_TRBCTL_NORMAL | DWC3_TRB_CTRL_CSP | DWC3_TRB_CTRL_ISP_IMI |
           DWC3_TRB_CTRL_IOC | DWC3_TRB_CTRL_LST;
    __asm__ volatile("dsb sy" ::: "memory");
    t[3] |= DWC3_TRB_CTRL_HWO;
    usbCacheRange(hw.dmaVirt + DMA_EP2_TRB_OFF, 64u, 1);
    uint32_t raw = 0;
    if (epCmd(hw, 2, DWC3_DEPCMD_STARTTRANSFER, static_cast<uint32_t>(trbPa >> 32),
              static_cast<uint32_t>(trbPa), 0, &raw) == 0) {
        hw.ep2RscIdx = DWC3_DEPCMD_RSC_IDX(raw);
        hw.ep2Armed  = true;
    }
}

static bool startBulkIn(UsbHw &hw, const uint8_t *data, uint32_t len) {
    if (!hw.configured || hw.ep3Busy || len == 0 || len > DMA_EP3_MAX_CHUNK) return false;
    memcpy(hw.dmaVirt + DMA_EP3_BUF_OFF, data, len);
    usbCacheRange(hw.dmaVirt + DMA_EP3_BUF_OFF, len, 0);
    volatile uint32_t *t0 = reinterpret_cast<volatile uint32_t *>(hw.dmaVirt + DMA_EP3_TRB_OFF);
    const uint64_t bufPa = hw.dmaPhys + DMA_EP3_BUF_OFF;
    const uint64_t trbPa = hw.dmaPhys + DMA_EP3_TRB_OFF;
    const bool needZlp = (len % hw.bulkMps) == 0u;
    if (needZlp) {
        volatile uint32_t *t1 = t0 + 4;
        t1[0] = static_cast<uint32_t>(bufPa);
        t1[1] = static_cast<uint32_t>(bufPa >> 32);
        t1[2] = 0u;
        t1[3] = DWC3_TRBCTL_NORMAL | DWC3_TRB_CTRL_ISP_IMI | DWC3_TRB_CTRL_IOC |
                DWC3_TRB_CTRL_LST | DWC3_TRB_CTRL_HWO;
        __asm__ volatile("dsb sy" ::: "memory");
        t0[0] = static_cast<uint32_t>(bufPa);
        t0[1] = static_cast<uint32_t>(bufPa >> 32);
        t0[2] = len;
        t0[3] = DWC3_TRBCTL_NORMAL | DWC3_TRB_CTRL_ISP_IMI | DWC3_TRB_CTRL_CHN;
    } else {
        t0[0] = static_cast<uint32_t>(bufPa);
        t0[1] = static_cast<uint32_t>(bufPa >> 32);
        t0[2] = len;
        t0[3] = DWC3_TRBCTL_NORMAL | DWC3_TRB_CTRL_ISP_IMI | DWC3_TRB_CTRL_IOC | DWC3_TRB_CTRL_LST;
    }
    __asm__ volatile("dsb sy" ::: "memory");
    t0[3] |= DWC3_TRB_CTRL_HWO;
    usbCacheRange(hw.dmaVirt + DMA_EP3_TRB_OFF, 64u, 1);
    uint32_t raw = 0;
    if (epCmd(hw, 3, DWC3_DEPCMD_STARTTRANSFER, static_cast<uint32_t>(trbPa >> 32),
              static_cast<uint32_t>(trbPa), 0, &raw) == 0) {
        hw.ep3RscIdx  = DWC3_DEPCMD_RSC_IDX(raw);
        hw.ep3Busy    = true;
        hw.ep3ArmTick = nowMs();
        return true;
    }
    return false;
}

static void programEp0(UsbHw &hw) {
    (void)epCmd(hw, 0, DWC3_DEPCMD_DEPSTARTCFG, 0, 0, 0);
    const uint32_t cfg = DWC3_DEPCFG_EP_TYPE(0) | DWC3_DEPCFG_MAX_PACKET_SIZE(64) | DWC3_DEPCFG_FIFO_NUMBER(0);
    const uint32_t ev  = DWC3_DEPCFG_XFER_COMPLETE_EN | DWC3_DEPCFG_XFER_NOT_READY_EN;
    (void)epCmd(hw, 0, DWC3_DEPCMD_SETEPCONFIG, cfg, ev | DWC3_DEPCFG_EP_NUMBER(0), 0);
    (void)epCmd(hw, 0, DWC3_DEPCMD_SETTRANSFRESOURCE, DWC3_DEPXFERCFG_NUM_XFER_RES(1), 0, 0);
    (void)epCmd(hw, 1, DWC3_DEPCMD_SETEPCONFIG, cfg, ev | DWC3_DEPCFG_EP_NUMBER(1), 0);
    (void)epCmd(hw, 1, DWC3_DEPCMD_SETTRANSFRESOURCE, DWC3_DEPXFERCFG_NUM_XFER_RES(1), 0, 0);
    hw.wr(DWC3_DALEPENA, DWC3_DALEPENA_EP(0) | DWC3_DALEPENA_EP(1));
    ep0ArmSetup(hw);
}

static void enableDataEndpoints(UsbHw &hw) {
    endDepTransfer(hw, 2, hw.ep2RscIdx, hw.ep2Armed);
    endDepTransfer(hw, 3, hw.ep3RscIdx, hw.ep3Busy);
    (void)epCmd(hw, 0, DWC3_DEPCMD_DEPSTARTCFG | DWC3_DEPCMD_PARAM(2), 0, 0, 0);
    const uint32_t ev = DWC3_DEPCFG_XFER_COMPLETE_EN | DWC3_DEPCFG_XFER_IN_PROGRESS_EN;
    // dep2 = EP1 OUT (0x01), FIFO 0
    (void)epCmd(hw, 2, DWC3_DEPCMD_SETEPCONFIG,
                DWC3_DEPCFG_EP_TYPE(2) | DWC3_DEPCFG_MAX_PACKET_SIZE(hw.bulkMps) | DWC3_DEPCFG_FIFO_NUMBER(0),
                ev | DWC3_DEPCFG_EP_NUMBER(2), 0);
    (void)epCmd(hw, 2, DWC3_DEPCMD_SETTRANSFRESOURCE, DWC3_DEPXFERCFG_NUM_XFER_RES(1), 0, 0);
    // dep3 = EP1 IN (0x81), dedicated TX FIFO 1
    (void)epCmd(hw, 3, DWC3_DEPCMD_SETEPCONFIG,
                DWC3_DEPCFG_EP_TYPE(2) | DWC3_DEPCFG_MAX_PACKET_SIZE(hw.bulkMps) | DWC3_DEPCFG_FIFO_NUMBER(1),
                ev | DWC3_DEPCFG_EP_NUMBER(3), 0);
    (void)epCmd(hw, 3, DWC3_DEPCMD_SETTRANSFRESOURCE, DWC3_DEPXFERCFG_NUM_XFER_RES(1), 0, 0);
    // dep5 = EP2 IN (0x82), dedicated TX FIFO 2, bInterval=9 -> bInterval_m1=8
    (void)epCmd(hw, 5, DWC3_DEPCMD_SETEPCONFIG,
                DWC3_DEPCFG_EP_TYPE(3) | DWC3_DEPCFG_MAX_PACKET_SIZE(16) | DWC3_DEPCFG_FIFO_NUMBER(2),
                ev | (8u << 16) | DWC3_DEPCFG_EP_NUMBER(5), 0);
    (void)epCmd(hw, 5, DWC3_DEPCMD_SETTRANSFRESOURCE, DWC3_DEPXFERCFG_NUM_XFER_RES(1), 0, 0);
    hw.wr(DWC3_DALEPENA, hw.rd(DWC3_DALEPENA) |
          DWC3_DALEPENA_EP(2) | DWC3_DALEPENA_EP(3) | DWC3_DALEPENA_EP(5));
    armBulkOut(hw);
}

static unsigned buildStringDesc(unsigned idx, uint8_t *out) {
    if (idx == 0) {
        out[0] = 4; out[1] = 3; out[2] = 0x09; out[3] = 0x04;
        return 4;
    }
    if (idx >= 4) return 0;
    const char *s = kUsbStrings[idx];
    unsigned n = 0;
    while (s[n] && n < 60) ++n;
    out[0] = static_cast<uint8_t>(2 + 2 * n);
    out[1] = 3;
    for (unsigned i = 0; i < n; ++i) {
        out[2 + 2 * i] = static_cast<uint8_t>(s[i]);
        out[3 + 2 * i] = 0;
    }
    return 2 + 2 * n;
}

static void handleEp0Setup(UsbHw &hw) {
    const uint8_t *setup = hw.dmaVirt + DMA_EP0_BUF_OFF;
    const uint8_t rt   = setup[0];
    const uint8_t req  = setup[1];
    const uint16_t val = static_cast<uint16_t>(setup[2] | (setup[3] << 8));
    const uint16_t len = static_cast<uint16_t>(setup[6] | (setup[7] << 8));

    hw.ep0Three     = (len != 0);
    hw.ep0In        = hw.ep0Three && ((rt & 0x80u) != 0u);
    hw.ep0Zlp       = false;
    hw.ep0StatusDep = hw.ep0In ? 0u : 1u;

    uint8_t *out = hw.dmaVirt + DMA_EP0_BUF_OFF;
    unsigned resp = 0;
    bool stall = false;

    if ((rt & 0x60u) == 0u) {
        switch (req) {
        case 0x00:  // GET_STATUS
            out[0] = 0; out[1] = 0; resp = 2; break;
        case 0x01:  // CLEAR_FEATURE
        case 0x03:  // SET_FEATURE
        case 0x0B:  // SET_INTERFACE
            break;
        case 0x05:  // SET_ADDRESS
            hw.wr(DWC3_DCFG, (hw.rd(DWC3_DCFG) & ~DWC3_DCFG_DEVADDR_MASK) | DWC3_DCFG_DEVADDR(val & 0x7Fu));
            break;
        case 0x06: {  // GET_DESCRIPTOR
            const unsigned dtype = val >> 8;
            if (dtype == 1u) {
                memcpy(out, kUsbCdcDeviceDesc, sizeof(kUsbCdcDeviceDesc));
                resp = sizeof(kUsbCdcDeviceDesc);
            } else if (dtype == 2u) {
                resp = usb_cdc_build_config_desc(out, hw.bulkMps);
            } else if (dtype == 3u) {
                resp = buildStringDesc(val & 0xFFu, out);
                if (!resp) stall = true;
            } else if (dtype == 6u) {  // DEVICE_QUALIFIER
                static const uint8_t kQual[10] = {10, 6, 0x00, 0x02, 0x02, 0x02, 0x00, 64, 1, 0};
                memcpy(out, kQual, 10);
                resp = 10;
            } else {
                stall = true;
            }
            break;
        }
        case 0x08:  // GET_CONFIGURATION
            out[0] = hw.configured; resp = 1; break;
        case 0x09:  // SET_CONFIGURATION
            hw.configured = static_cast<uint8_t>(val & 0xFFu);
            if (hw.configured) {
                ++hw.usbCfgCount;
                if (hw.usbCfgCount == 1u) {
                    logStage("usb: host SET_CONFIGURATION=1 complete");
                }
                enableDataEndpoints(hw);
            }
            break;
        default:
            stall = true; break;
        }
    } else if ((rt & 0x60u) == 0x20u) {
        if (req == 0x21u) {  // GET_LINE_CODING
            memcpy(out, hw.lineCoding, 7);
            resp = 7;
        } else if (req == 0x20u) {  // SET_LINE_CODING (7B OUT stage)
            resp = len > 64u ? 64u : len;
        } else if (req == 0x22u) {  // SET_CONTROL_LINE_STATE
            const bool prevDtr = (hw.lineState & 1u) != 0u;
            hw.lineState = val;
            if (val & 1u) {
                hw.hostReady = true;
                if (!prevDtr) hw.needReplay = true;
            } else {
                hw.hostReady = false;
            }
        } else if (req == 0x23u) {  // SEND_BREAK
        } else {
            stall = true;
        }
    } else {
        stall = true;
    }

    if (stall) {
        ep0Restart(hw);
        return;
    }
    if (!hw.ep0Three) {
        hw.ep0Stage = 2;
        return;
    }
    if (hw.ep0In) {
        if (resp > len) resp = len;
        hw.ep0Zlp = (resp != 0u) && (resp < len) && ((resp % 64u) == 0u);
        ep0StartData(hw, 1u, resp);
    } else {
        ep0StartData(hw, 0u, len > 64u ? 64u : len);
    }
}

struct TerminalSession {
    UsbHw hw;
    UsbReplyRing reply;
    UsbScreenState screen;
    IOBufferMemoryDescriptor *replyMem = nullptr;
    IOBufferMemoryDescriptor *rgbMem   = nullptr;
    OSSharedPtr<IOMemoryMap> ramoopsMap;
    volatile const uint8_t *ramoops    = nullptr;
    uint32_t lastRamoopsPos            = 0;
    bool pendingFastboot               = false;   // a reset is queued (rebootKind says which)
    unsigned rebootKind                = 0;       // 1 = fastboot (reason marked), 2 = plain (PSCI only)
    UsbFileXfer xfer                   = {};
    bool pendingXdci                   = false;
    uint32_t pendingXdciSec            = 0;
    char cmdLine[256]                  = {};
    unsigned cmdLen                    = 0;
};

static void replayRamoops(TerminalSession &s, bool currentBootOnly) {
    if (!s.ramoops) return;
    volatile const uint32_t *hdr = reinterpret_cast<volatile const uint32_t *>(s.ramoops);
    const uint32_t sig = hdr[0], start = hdr[1], size = hdr[2];
    if (sig != J716F_RAMOOPS_SIG || start >= J716F_RAMOOPS_DATA || size > J716F_RAMOOPS_DATA) return;
    s.lastRamoopsPos = start;
    if (size == 0u) return;

    const volatile uint8_t *ring = s.ramoops + J716F_RAMOOPS_HEAD;
    const uint32_t oldest = (size < J716F_RAMOOPS_DATA) ? 0u : start;
    uint32_t beginOff = 0u;
    if (currentBootOnly) {
        static const char kMarker[] = "boot_progress_init";
        const uint32_t mLen = sizeof(kMarker) - 1u;
        for (uint32_t pos = size; pos >= mLen; --pos) {
            const uint32_t base = pos - mLen;
            bool match = true;
            for (uint32_t k = 0; k < mLen; ++k) {
                if (ring[(oldest + base + k) % J716F_RAMOOPS_DATA] != static_cast<uint8_t>(kMarker[k])) {
                    match = false; break;
                }
            }
            if (match) {
                beginOff = base > 6u ? base - 6u : 0u;
                break;
            }
            if (pos == mLen) break;
        }
    }
    const uint32_t toSend = size - beginOff;
    if (toSend > s.reply.freeBytes() - 256u) {
        beginOff = size - (s.reply.freeBytes() - 512u);
    }
    s.reply.writeStr("\r\n[usb] === ruan ramoops replay begin ===\r\n");
    for (uint32_t i = beginOff; i < size; ++i) {
        const uint8_t ch = ring[(oldest + i) % J716F_RAMOOPS_DATA];
        (void)s.reply.write(&ch, 1u);
    }
    s.reply.writeStr("\r\n[usb] === ruan ramoops replay end ===\r\n");
}

static unsigned gRebootAllowed = 0;   // ruan-usbdbg-reboot=1

#include "UsbDebugGpu.h"   // ruan: the gpu command (gpu-dev stage S1)

static void handleCommand(TerminalSession &s, const char *raw) {
    while (*raw == ' ' || *raw == '\t') ++raw;
    if (!*raw) return;
    char buf[512];
    if (usbGpuCommand(s, raw, buf, sizeof(buf))) return;

    if (strEq(raw, "ping")) {
        s.reply.writeStr("[usb] PONG ruan\r\n");
    } else if (strEq(raw, "features") || strEq(raw, "help")) {
        s.reply.writeStr("FEATURES: ping status bootargs display usb touch battery wifi audio replay screen.snapshot screen.start screen.stop screen.configure reboot.status reboot reboot.fastboot ls cat dmesg gpu\r\n");
    } else if (strEq(raw, "wifi") || strEq(raw, "wlan")) {
        if (&ruan_wifi_status_str && ruan_wifi_status_str) {
            snprintf(buf, sizeof(buf), "[usb] WIFI: %s\r\n", ruan_wifi_status_str());
        } else {
            snprintf(buf, sizeof(buf), "[usb] WIFI: driver not linked\r\n");
        }
        s.reply.writeStr(buf);
    } else if (strEq(raw, "audio") || strEq(raw, "sound")) {
        if (&ruan_audio_status_str && ruan_audio_status_str) {
            snprintf(buf, sizeof(buf), "[usb] AUDIO: %s\r\n", ruan_audio_status_str());
        } else {
            snprintf(buf, sizeof(buf), "[usb] AUDIO: driver not linked\r\n");
        }
        s.reply.writeStr(buf);
    } else if (strEq(raw, "backlight") || strStarts(raw, "backlight ")) {
        // "backlight" shows the SY7758 state; "backlight N" (16..4095) writes the brightness and reads it back
        if (!&g_ruan_backlight || !&ruan_backlight_set_level) {
            s.reply.writeStr("[usb] BACKLIGHT: driver not linked\r\n");
        } else if (strStarts(raw, "backlight reg ") && &ruan_backlight_reg) {
            // "backlight reg R" reads SY7758 register R; "backlight reg R V" writes V then reads it back
            const char *p = raw + 14;
            bool okr = false, okv = false;
            const uint32_t reg = parseUint(p, &okr);
            const uint32_t val = parseUint(p, &okv);
            const int got = okr && reg <= 0xff && (!okv || val <= 0xff) ? ruan_backlight_reg((uint8_t)reg, okv ? (int)val : -1) : -2;
            snprintf(buf, sizeof(buf), "[usb] BACKLIGHT REG %02x%s = %d (0x%02x)\r\n", reg & 0xff, okv ? " written" : "", got, got & 0xff);
            s.reply.writeStr(buf);
        } else {
            const char *p = raw + 9;
            bool ok = false;
            const uint32_t level = parseUint(p, &ok);
            int rc = 0;
            if (ok) rc = ruan_backlight_set_level(level);
            snprintf(buf, sizeof(buf),
                     "[usb] BACKLIGHT: %s%s rc=%d level=%u ready=%d id=%02x updates=%llu errors=%u last_irq=%08x status=%s\r\n",
                     ok ? "set " : "", ok ? "done" : "", rc, g_ruan_backlight.current_level, g_ruan_backlight.ready,
                     g_ruan_backlight.dev_id, (unsigned long long)g_ruan_backlight.updates_count, g_ruan_backlight.errors,
                     g_ruan_backlight.last_irq, g_ruan_backlight.status);
            s.reply.writeStr(buf);
        }
    } else if (strEq(raw, "battery") || strEq(raw, "power")) {
        // g_ruan_battery declared at file scope in extern "C" block above (weak_import)
        if (&g_ruan_battery) {
            // 0 means "not measured" in the driver: say so instead of printing 0 mA / 0 C
            char cur[16] = "unknown", temp[16] = "unknown";
            if (g_ruan_battery.current_ua) snprintf(cur, sizeof(cur), "%dmA", g_ruan_battery.current_ua / 1000);
            if (g_ruan_battery.temperature_hundredths) snprintf(temp, sizeof(temp), "%dC", g_ruan_battery.temperature_hundredths / 100);
            snprintf(buf, sizeof(buf),
                     "[usb] BATTERY: present=%d level=%d%% (estimated from voltage) volt=%dmV cur=%s temp=%s ext=%d chg=%d full=%d"
                     " (voltage source: see 'battery:' line in log)\r\n",
                     g_ruan_battery.present,
                     g_ruan_battery.percent_hundredths / 100,
                     g_ruan_battery.voltage_uv / 1000,
                     cur, temp,
                     g_ruan_battery.external,
                     g_ruan_battery.status == 1,
                     g_ruan_battery.status == 4);
        } else {
            snprintf(buf, sizeof(buf), "[usb] BATTERY: driver not linked\r\n");
        }
        s.reply.writeStr(buf);
    } else if (strEq(raw, "info") || strEq(raw, "uptime") || strEq(raw, "status")) {
        const uint64_t ms = nowMs();
        snprintf(buf, sizeof(buf),
                 "[usb] board=ruan soc=SM7435 uptime=%llu.%03llus usb_events=%u resets=%u frames_copied=%llu\r\n",
                 ms / 1000ULL, ms % 1000ULL, s.hw.usbEvents, s.hw.usbResets,
                 &native_legacy_copy_n ? (unsigned long long)native_legacy_copy_n : 0ULL);
        s.reply.writeStr(buf);
        snprintf(buf, sizeof(buf), "[usb] %s\r\n[usb] %s\r\n", gUsbHudLine0, gUsbHudLine1);
        s.reply.writeStr(buf);
    } else if (strEq(raw, "bootargs")) {
        snprintf(buf, sizeof(buf), "[usb] bootargs=%s\r\n", PE_boot_args());
        s.reply.writeStr(buf);
    } else if (strEq(raw, "display")) {
        uint32_t f_sub = 0, f_ret = 0;
        if (&native_adreno_fences) native_adreno_fences(&f_sub, &f_ret);
        snprintf(buf, sizeof(buf),
                 "[usb] FB: stage=%u %ux%u phys=0x%llx virt=0x%llx bytes=0x%llx copies=%llu gpu_blits=%llu gpu_ticks=%u\r\n"
                 "[usb] FB SWAP: accepted=%u rejected=%u early_retire=%u fallbacks=%u last_fb_reason=%d wraps=%u fences_sub=%u fences_ret=%u\r\n"
                 "[usb] VSYNC: arm=%llu tick=%llu no_client=%llu missed=%llu start=%llu req=%llu\r\n",
                 &native_legacy_stage ? native_legacy_stage : 0u,
                 &native_legacy_gop_width ? native_legacy_gop_width : 0u,
                 &native_legacy_gop_height ? native_legacy_gop_height : 0u,
                 &native_legacy_gop_physical ? (unsigned long long)native_legacy_gop_physical : 0ULL,
                 &native_legacy_gop_virtual ? (unsigned long long)native_legacy_gop_virtual : 0ULL,
                 &native_legacy_gop_bytes ? (unsigned long long)native_legacy_gop_bytes : 0ULL,
                 &native_legacy_copy_n ? (unsigned long long)native_legacy_copy_n : 0ULL,
                 &native_legacy_gpu_blits ? (unsigned long long)native_legacy_gpu_blits : 0ULL,
                 &native_legacy_gpu_last_ticks ? native_legacy_gpu_last_ticks : 0u,
                 &native_legacy_swap_accepted_count ? native_legacy_swap_accepted_count : 0u,
                 &native_legacy_swap_rejected_count ? native_legacy_swap_rejected_count : 0u,
                 &native_legacy_early_retires ? native_legacy_early_retires : 0u,
                 &native_legacy_gpu_fallbacks ? native_legacy_gpu_fallbacks : 0u,
                 &native_legacy_gpu_last_fallback_reason ? native_legacy_gpu_last_fallback_reason : 0,
                 &ruan_gpu_ring_wraps ? ruan_gpu_ring_wraps() : 0u,
                 f_sub, f_ret,
                 &native_legacy_vsync_events ? (unsigned long long)native_legacy_vsync_events[0] : 0ULL,
                 &native_legacy_vsync_events ? (unsigned long long)native_legacy_vsync_events[1] : 0ULL,
                 &native_legacy_vsync_events ? (unsigned long long)native_legacy_vsync_events[2] : 0ULL,
                 &native_legacy_vsync_events ? (unsigned long long)native_legacy_vsync_events[3] : 0ULL,
                 &native_legacy_vsync_events ? (unsigned long long)native_legacy_vsync_events[4] : 0ULL,
                 &native_legacy_vsync_events ? (unsigned long long)native_legacy_vsync_events[5] : 0ULL);
        s.reply.writeStr(buf);
    } else if (strStarts(raw, "display.stress")) {
        const char *p = raw + 14;
        bool ok = false;
        uint32_t count = parseUint(p, &ok);
        if (!ok || count == 0) count = 25;
        if (count > 500) count = 500;
        int last_rc = 0;
        uint32_t success = 0;
        uint64_t t0 = 0, t1 = 0;
        if (&ruan_gpu_dma_blit_frame) {
            __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(t0));
            for (uint32_t i = 0; i < count; i++) {
                int rc = ruan_gpu_dma_blit_frame(0x50000000u, 0x50000000u, 1600 * 2560);
                if (rc == 0) {
                    success++;
                    if (&native_legacy_gpu_blits) native_legacy_gpu_blits = native_legacy_gpu_blits + 1;
                } else {
                    last_rc = rc;
                    break;
                }
            }
            __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(t1));
        }
        uint32_t f_sub = 0, f_ret = 0;
        if (&native_adreno_fences) native_adreno_fences(&f_sub, &f_ret);
        snprintf(buf, sizeof(buf),
                 "[usb] DISPLAY STRESS: n=%u/%u rc=%d ticks=%llu wraps=%u fences_sub=%u fences_ret=%u\r\n",
                 success, count, last_rc, (unsigned long long)(t1 - t0),
                 &ruan_gpu_ring_wraps ? ruan_gpu_ring_wraps() : 0u,
                 f_sub, f_ret);
        s.reply.writeStr(buf);
    } else if (strEq(raw, "touch.tap")) {
        if (&hakios_touch_post) {
            hakios_touch_post(1, 0, 32768, 32768); // HAKIOS_TOUCH_DOWN
            for (volatile int i = 0; i < 50000; i++) {}
            hakios_touch_post(3, 0, 32768, 32768); // HAKIOS_TOUCH_UP
            s.reply.writeStr("[usb] touch.tap: posted down+up at center\r\n");
        } else {
            s.reply.writeStr("[usb] touch.tap: hakios_touch_post missing\r\n");
        }
    } else if (strEq(raw, "touch.swipe")) {
        if (&hakios_touch_post) {
            hakios_touch_post(1, 0, 32768, 55000); // HAKIOS_TOUCH_DOWN
            for (uint32_t y = 55000; y >= 15000; y -= 5000) {
                for (volatile int i = 0; i < 20000; i++) {}
                hakios_touch_post(2, 0, 32768, y);     // HAKIOS_TOUCH_MOVE
            }
            hakios_touch_post(3, 0, 32768, 15000); // HAKIOS_TOUCH_UP
            s.reply.writeStr("[usb] touch.swipe: posted upward swipe (unlock)\r\n");
        } else {
            s.reply.writeStr("[usb] touch.swipe: hakios_touch_post missing\r\n");
        }
    } else if (strEq(raw, "button.lock") || strEq(raw, "button.power")) {
        if (&hakios_touch_post) {
            hakios_touch_post(4, 1, 0, 0); // HAKIOS_BUTTON_DOWN, HAKIOS_BUTTON_LOCK
            for (volatile int i = 0; i < 50000; i++) {}
            hakios_touch_post(5, 1, 0, 0); // HAKIOS_BUTTON_UP, HAKIOS_BUTTON_LOCK
            s.reply.writeStr("[usb] button.lock: toggled lock/power key\r\n");
        } else {
            s.reply.writeStr("[usb] button.lock: hakios_touch_post missing\r\n");
        }
    } else if (strEq(raw, "touch") || strEq(raw, "touch.status") || strEq(raw, "input.status")) {
        snprintf(buf, sizeof(buf), "[usb] INPUT: touch=%u buttons=%u %s\r\n",
                 &ruan_touch_events ? ruan_touch_events : 0u,
                 &ruan_button_events ? ruan_button_events : 0u,
                 &ruan_input_row ? ruan_input_row : "");
        s.reply.writeStr(buf);
    } else if (strEq(raw, "usb") || strEq(raw, "usb.status")) {
        snprintf(buf, sizeof(buf),
                 "[usb] USB: cfg=%u mps=%u dtr=%u dsts=0x%08x gctl=0x%08x dctl=0x%08x phy2=0x%08x qhs=0x%08x qss=0x%08x events=%u resets=%u\r\n",
                 s.hw.configured, s.hw.bulkMps, s.hw.lineState & 1u,
                 s.hw.rd(DWC3_DSTS), s.hw.rd(DWC3_GCTL), s.hw.rd(DWC3_DCTL),
                 s.hw.rd(DWC3_GUSB2PHYCFG(0)), s.hw.rd(QSCRATCH_HS_PHY_CTRL),
                 s.hw.rd(QSCRATCH_SS_PHY_CTRL),
                 s.hw.usbEvents, s.hw.usbResets);
        s.reply.writeStr(buf);
    } else if (strEq(raw, "replay")) {
        replayRamoops(s, false);
    } else if (strEq(raw, "screen.snapshot")) {
        (void)usbCaptureAndQueueGsc1(s.screen, s.reply, true);
    } else if (strEq(raw, "screen.start")) {
        s.screen.streaming = true;
        s.screen.nextFrameTick = 0;
        s.reply.writeStr("GIULIA SCREEN: streaming enabled\r\n");
    } else if (strEq(raw, "screen.stop")) {
        s.screen.streaming = false;
        usbQueueGsc1Stop(s.screen, s.reply);
        s.reply.writeStr("GIULIA SCREEN: streaming stopped\r\n");
    } else if (strStarts(raw, "screen.configure")) {
        const char *p = raw + 16;
        bool ok1 = false, ok2 = false;
        const uint32_t edge = parseUint(p, &ok1);
        const uint32_t fps  = parseUint(p, &ok2);
        if (ok1 && edge >= 160u && edge <= 2780u) s.screen.maxEdge = edge;
        if (ok2 && fps >= 1u && fps <= 30u) s.screen.maxFps = fps;
        snprintf(buf, sizeof(buf), "GIULIA SCREEN: configured max_size=%u max_fps=%u\r\n",
                 s.screen.maxEdge, s.screen.maxFps);
        s.reply.writeStr(buf);
    } else if (strEq(raw, "reboot.status")) {
        snprintf(buf, sizeof(buf), "GIULIA REBOOT: pending=%u allowed=%u\r\n", s.pendingFastboot ? 1u : 0u, gRebootAllowed);
        s.reply.writeStr(buf);
    } else if (strStarts(raw, "ls ")) {
        usbLs(s.reply, raw + 3);
    } else if (strStarts(raw, "cat ")) {
        usbCatStart(s.xfer, s.reply, raw + 4);
    } else if (strEq(raw, "dmesg")) {
        usbDmesgStart(s.xfer, s.reply);
    } else if (strEq(raw, "reboot") || strEq(raw, "reboot.fastboot")) {
        const bool fastboot = strEq(raw, "reboot.fastboot");
        (void)PE_parse_boot_argn("ruan-usbdbg-reboot", &gRebootAllowed, sizeof(gRebootAllowed));
        if (!gRebootAllowed) {
            s.reply.writeStr("GIULIA REBOOT: refused (boot with ruan-usbdbg-reboot=1)\r\n");
            return;
        }
        if (s.pendingFastboot) {
            s.reply.writeStr("GIULIA REBOOT: already queued\r\n");
            return;
        }
        s.screen.streaming = false;
        s.hw.needReplay    = false;
        if (s.xfer.active) usbFileEnd(s.xfer);
        if (fastboot) {
            // Every step is reported before the next one acts, so a hang or a reset shows where it happened.
            char text[160];
            if (!&boot_reset_probe || !&boot_reset_mark_bootloader) {
                s.reply.writeStr("GIULIA REBOOT: step 0 refused: no package/BootReset.c in this kernel\r\n");
                return;
            }
            s.reply.writeStr("GIULIA REBOOT: step 1 probe (PMIC arbiter, reboot-reason cell)\r\n");
            int rc = boot_reset_probe(text, sizeof(text));
            snprintf(buf, sizeof(buf), "GIULIA REBOOT: step 1 rc=%d %s\r\n", rc, text);
            s.reply.writeStr(buf);
            if (rc) { s.reply.writeStr("GIULIA REBOOT: stopped before any write\r\n"); return; }
            s.reply.writeStr("GIULIA REBOOT: step 2 mark bootloader + read back\r\n");
            rc = boot_reset_mark_bootloader(text, sizeof(text));
            snprintf(buf, sizeof(buf), "GIULIA REBOOT: step 2 rc=%d %s\r\n", rc, text);
            s.reply.writeStr(buf);
            if (rc) { s.reply.writeStr("GIULIA REBOOT: stopped before PSCI\r\n"); return; }
        }
        s.reply.writeStr(fastboot ? "GIULIA REBOOT: step 3 PSCI SYSTEM_RESET once this line is sent (target fastboot)\r\n"
                                  : "GIULIA REBOOT: PSCI SYSTEM_RESET once this line is sent, no reboot reason (target: normal boot)\r\n");
        logStage(fastboot ? "usb: reboot.fastboot by host" : "usb: reboot by host");
        s.rebootKind      = fastboot ? 1u : 2u;
        s.pendingFastboot = true;
    } else {
        snprintf(buf, sizeof(buf), "[usb] unsupported command: %s\r\n", raw);
        s.reply.writeStr(buf);
    }
}

static void handleDepEvent(TerminalSession &s, uint32_t ev) {
    UsbHw &hw = s.hw;
    const unsigned dep    = (ev >> 1) & 0x1Fu;
    const unsigned kind   = (ev >> 6) & 0x0Fu;
    const unsigned status = (ev >> 12) & 0x0Fu;

    if (dep <= 1u) {
        if (kind == DWC3_DEPEVT_XFERNOTREADY) {
            if (status == DEPEVT_STATUS_CONTROL_STATUS && (hw.ep0Stage == 2 || hw.ep0Stage == 1)) {
                ep0StartStatus(hw, dep <= 1u ? dep : hw.ep0StatusDep);
            }
            return;
        }
        if (kind != DWC3_DEPEVT_XFERCOMPLETE) return;
        if (hw.ep0Stage == 0) {
            usbCacheRange(hw.dmaVirt + DMA_EP0_TRB_OFF, 64u, 2);
            usbCacheRange(hw.dmaVirt + DMA_EP0_BUF_OFF, 64u, 2);
            handleEp0Setup(hw);
        } else if (hw.ep0Stage == 1) {
            usbCacheRange(hw.dmaVirt + DMA_EP0_TRB_OFF, 64u, 2);
            bool setupPending = false;
            for (unsigned i = 0; i < hw.ep0Trbs; ++i) {
                if (DWC3_TRB_SIZE_TRBSTS(ep0TrbPtr(hw, i)[2]) == DWC3_TRBSTS_SETUP_PENDING) {
                    setupPending = true;
                }
            }
            if (!hw.ep0In && hw.ep0Armed == 7u) {
                usbCacheRange(hw.dmaVirt + DMA_EP0_BUF_OFF, 64u, 2);
                memcpy(hw.lineCoding, hw.dmaVirt + DMA_EP0_BUF_OFF, 7);
            }
            if (setupPending) {
                ep0ArmSetup(hw);
                return;
            }
            hw.ep0Stage = 2;
        } else if (hw.ep0Stage == 3) {
            ep0ArmSetup(hw);
        }
        return;
    }

    if (dep == 2u && kind == DWC3_DEPEVT_XFERCOMPLETE) {
        hw.ep2Armed = false;
        hw.ep2RscIdx = 0u;
        usbCacheRange(hw.dmaVirt + DMA_EP2_TRB_OFF, 64u, 2);
        usbCacheRange(hw.dmaVirt + DMA_EP2_BUF_OFF, hw.bulkMps, 2);
        volatile uint32_t *t = reinterpret_cast<volatile uint32_t *>(hw.dmaVirt + DMA_EP2_TRB_OFF);
        const uint32_t rem = t[2] & DWC3_TRB_SIZE_MASK;
        const uint32_t got = (rem <= hw.bulkMps) ? (hw.bulkMps - rem) : 0u;
        const uint8_t *rx = hw.dmaVirt + DMA_EP2_BUF_OFF;
        hw.hostReady = true;
        for (uint32_t i = 0; i < got; ++i) {
            const char c = static_cast<char>(rx[i]);
            if (c == '\r' || c == '\n') {
                if (s.cmdLen > 0) {
                    s.cmdLine[s.cmdLen] = '\0';
                    handleCommand(s, s.cmdLine);
                    s.cmdLen = 0;
                }
            } else if (c >= 0x20 && c < 0x7F && s.cmdLen + 1u < sizeof(s.cmdLine)) {
                s.cmdLine[s.cmdLen++] = c;
            }
        }
        armBulkOut(hw);
        return;
    }

    if (dep == 3u && kind == DWC3_DEPEVT_XFERCOMPLETE) {
        hw.ep3Busy   = false;
        hw.ep3RscIdx = 0u;
        return;
    }
}

static void pollUsbEvents(TerminalSession &s) {
    UsbHw &hw = s.hw;
    volatile uint32_t *ring = reinterpret_cast<volatile uint32_t *>(hw.dmaVirt + DMA_EVT_OFF);
    for (unsigned guard = 0; guard < 64; ++guard) {
        const uint32_t count = hw.rd(DWC3_GEVNTCOUNT(0)) & 0xFFFCu;
        if (!count) break;
        if (count > 4096u) {
            hw.evtOff = (hw.evtOff + count) % 4096u;
            hw.wr(DWC3_GEVNTCOUNT(0), count);
            continue;
        }
        usbCacheRange(hw.dmaVirt + DMA_EVT_OFF, 4096u, 2);
        uint32_t left = count;
        while (left >= 4u) {
            const uint32_t ev = ring[hw.evtOff / 4u];
            ++hw.usbEvents;
            if (ev & 1u) {
                const unsigned type = (ev >> 8) & 0x0Fu;
                if (type == DWC3_DEV_EVENT_RESET) {
                    ++hw.usbResets;
                    if (hw.usbResets == 1u) {
                        logStage("usb: first host USB_RESET received");
                    }
                    endDepTransfer(hw, 2, hw.ep2RscIdx, hw.ep2Armed);
                    endDepTransfer(hw, 3, hw.ep3RscIdx, hw.ep3Busy);
                    hw.configured = 0;
                    hw.hostReady  = false;
                    hw.wr(DWC3_DCFG, hw.rd(DWC3_DCFG) & ~DWC3_DCFG_DEVADDR_MASK);
                    ep0Restart(hw);
                } else if (type == DWC3_DEV_EVENT_CONNECT_DONE) {
                    const uint32_t spd = hw.rd(DWC3_DSTS) & DWC3_DSTS_CONNECTSPD_MASK;
                    hw.bulkMps = (spd == DWC3_DCFG_HIGHSPEED) ? 512u : 64u;
                } else if (type == DWC3_DEV_EVENT_DISCONNECT) {
                    endDepTransfer(hw, 2, hw.ep2RscIdx, hw.ep2Armed);
                    endDepTransfer(hw, 3, hw.ep3RscIdx, hw.ep3Busy);
                    hw.configured = 0;
                    hw.hostReady  = false;
                }
            } else {
                handleDepEvent(s, ev);
            }
            hw.evtOff = (hw.evtOff + 4u) % 4096u;
            left -= 4u;
        }
        hw.wr(DWC3_GEVNTCOUNT(0), count);
    }
}

// Returns only when BootReset refused (the reason is logged); the caller then reconnects.
// The reply ring has been sent (the caller waits for it): drop the pull-up so the host closes the tty, then PSCI SYSTEM_RESET.
// rebootKind 1: the reboot-reason cell already says "bootloader" (boot_reset_mark_bootloader, read back); 2 leaves it alone.
__attribute__((noreturn)) static void executeWarmFastbootReboot(UsbHw &hw) {
    hw.wr(DWC3_DCTL, hw.rd(DWC3_DCTL) & ~DWC3_DCTL_RUN_STOP);
    IOSleep(100);
    __asm__ volatile("msr daifset, #3" ::: "memory");
    {
        register uint64_t x0 __asm__("x0") = J716F_PSCI_SYSTEM_RESET;
        register uint64_t x1 __asm__("x1") = 0;
        register uint64_t x2 __asm__("x2") = 0;
        register uint64_t x3 __asm__("x3") = 0;
        __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3)
                         : : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11",
                             "x12", "x13", "x14", "x15", "x16", "x17", "memory");
    }
    for (;;) __asm__ volatile("wfe");
}

static bool bringUpController(TerminalSession &s) {
    UsbHw &hw = s.hw;
    if (!hw.dmaVirt) {
        char why[96];
        hw.dmaDesc = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(
            kernel_task,
            static_cast<IOOptionBits>(kIODirectionInOut) | static_cast<IOOptionBits>(kIOMemoryPhysicallyContiguous),
            DMA_TOTAL_BYTES, 0xFFFFFFF000ULL);
        const IOReturn prep = hw.dmaDesc ? hw.dmaDesc->prepare() : kIOReturnNoMemory;
        addr64_t segLen = 0;
        if (hw.dmaDesc && prep == kIOReturnSuccess) {
            hw.dmaPhys = hw.dmaDesc->getPhysicalSegment(0, &segLen);
            hw.dmaVirt = static_cast<uint8_t *>(hw.dmaDesc->getBytesNoCopy());
        }
        if (!hw.dmaVirt || !hw.dmaPhys || segLen < DMA_TOTAL_BYTES) {
            snprintf(why, sizeof(why), "usb: iobmd %s prep=0x%x seg=0x%llx; arena 0x%llx",
                     hw.dmaDesc ? "ok" : "null", prep, (unsigned long long)segLen, RUAN_USB_DMA_ARENA);
            logStage(why);
            if (hw.dmaDesc) {
                if (prep == kIOReturnSuccess) hw.dmaDesc->complete();
                hw.dmaDesc->release();
                hw.dmaDesc = nullptr;
            }
            // Normal non-cacheable: unaligned CPU accesses (memset/memcpy) are legal and the controller sees every write.
            IODeviceMemory *mem = IODeviceMemory::withRange(RUAN_USB_DMA_ARENA, DMA_TOTAL_BYTES);
            if (mem) {
                hw.dmaMap = OSSharedPtr<IOMemoryMap>(mem->map(kIOMapAnywhere | kIOMapWriteCombineCache), OSNoRetain);
                mem->release();
            }
            hw.dmaVirt = hw.dmaMap ? reinterpret_cast<uint8_t *>(hw.dmaMap->getVirtualAddress()) : nullptr;
            hw.dmaPhys = hw.dmaVirt ? RUAN_USB_DMA_ARENA : 0;
            if (!hw.dmaVirt) {
                logStage("usb: dma arena map failed");
                return false;
            }
        }
    }
    memset(hw.dmaVirt, 0, DMA_TOTAL_BYTES);
    usbCacheRange(hw.dmaVirt, DMA_TOTAL_BYTES, 1);
    {
        char ok[80];
        snprintf(ok, sizeof(ok), "usb: dma %s pa=0x%llx", hw.dmaDesc ? "iobmd" : "arena", (unsigned long long)hw.dmaPhys);
        logStage(ok);
    }

    if (!hw.smmu) {
        (void)usbConfigureSmmuBypass(hw);
    }
    if (!usbGccAndPhyInit(hw)) {
        logStage("usb: gcc/phy init failed");
        return false;
    }

    if (!hw.core) {
        hw.core = reinterpret_cast<volatile uint32_t *>(
            mapRangeUncached(J716F_USB0_CORE_BASE, J716F_USB0_CORE_SIZE, hw.coreMap));
        if (!hw.core) {
            logStage("usb: core map failed");
            return false;
        }
    }

    const uint32_t gsnpsid = hw.rd(DWC3_GSNPSID);
    const uint32_t sid = gsnpsid & DWC3_GSNPSID_MASK;
    if (sid != DWC3_GSNPSID_USB3 && sid != DWC3_GSNPSID_USB31 && sid != DWC3_GSNPSID_USB31_3331) {
        char msg[96];
        snprintf(msg, sizeof(msg), "usb: unexpected GSNPSID=0x%08x", gsnpsid);
        logStage(msg);
        return false;
    }

    // 1. Switch QSCRATCH_GENERAL_CFG PIPE_UTMI_CLK_SEL if QMP SS PHY pipe_clk is off OR if forced into HS-only fallback (phyInitMode == 1).
    //    During normal UEFI boot, SSUsb1InitSSPhy (0x9094) succeeds and leaves pipe_clk running with QSCRATCH_GENERAL_CFG = 0.
    const bool pipeClkOff = (hw.grd(GCC_USB3_PRIM_PHY_PIPE_CLK) & GCC_BRANCH_CLK_OFF) != 0u;
    if (pipeClkOff || hw.phyInitMode == 1u) {
        hw.wr(QSCRATCH_GENERAL_CFG, hw.rd(QSCRATCH_GENERAL_CFG) | QSCRATCH_PIPE_UTMI_CLK_DIS);
        IODelay(100);
        hw.wr(QSCRATCH_GENERAL_CFG,
              (hw.rd(QSCRATCH_GENERAL_CFG) & ~0x200u) |
              QSCRATCH_PIPE_UTMI_CLK_SEL | QSCRATCH_PIPE3_PHYSTATUS_SW);
        IODelay(100);
        hw.wr(QSCRATCH_GENERAL_CFG, hw.rd(QSCRATCH_GENERAL_CFG) & ~QSCRATCH_PIPE_UTMI_CLK_DIS);
    }
    hw.wr(QSCRATCH_CGCTL, hw.rd(QSCRATCH_CGCTL) | 0x02u);

    // 2. OEM UsbfnDwc3Dxe VBUS + power-present override (0xee48..0xee94):
    //    Set QSCRATCH_HS_PHY_CTRL bits 20 & 28 and QSCRATCH_SS_PHY_CTRL bit 24 (LANE0_PWR_PRESENT) before DwcInitialize!
    hw.wr(QSCRATCH_HS_PHY_CTRL, hw.rd(QSCRATCH_HS_PHY_CTRL) | QSCRATCH_UTMI_OTG_VBUS_VALID);
    hw.wr(QSCRATCH_HS_PHY_CTRL, hw.rd(QSCRATCH_HS_PHY_CTRL) | QSCRATCH_SW_SESSVLD_SEL);
    hw.wr(QSCRATCH_SS_PHY_CTRL, hw.rd(QSCRATCH_SS_PHY_CTRL) | QSCRATCH_LANE0_PWR_PRESENT);

    // 3. OEM UsbfnDwc3Dxe DwcInitialize (0x39cc..0x40e0): device CSFTRST, then configure DWC3 core
    hw.wr(DWC3_DCTL, (hw.rd(DWC3_DCTL) & ~DWC3_DCTL_RUN_STOP) | DWC3_DCTL_CSFTRST);
    for (unsigned i = 0; i < 100000; ++i) {
        if ((hw.rd(DWC3_DCTL) & DWC3_DCTL_CSFTRST) == 0u) break;
        IODelay(5);
    }

    hw.wr(DWC3_DCTL, (hw.rd(DWC3_DCTL) & ~(0x1F000000u | DWC3_DCTL_RUN_STOP)) | 0x10F00000u);
    hw.wr(DWC3_GSBUSCFG0, hw.rd(DWC3_GSBUSCFG0) | 0x0Eu);
    hw.wr(DWC3_GSBUSCFG1, (hw.rd(DWC3_GSBUSCFG1) & ~0xF00u) | 0xE00u);

    // Clear ENBLSLPM (bit 8) and SUSPHY (bit 6) ONLY; preserve hardware PHYIF/USBTRDTIM straps (0x3aa0..0x3ad4)
    hw.wr(DWC3_GUSB2PHYCFG(0), hw.rd(DWC3_GUSB2PHYCFG(0)) & ~DWC3_GUSB2PHYCFG_ENBLSLPM);
    hw.wr(DWC3_GUSB2PHYCFG(0), hw.rd(DWC3_GUSB2PHYCFG(0)) & ~DWC3_GUSB2PHYCFG_SUSPHY);
    // Clear ELASTIC_BUFFER_MODE (bit 0) (0x3ae0..0x3b00)
    hw.wr(DWC3_GUSB3PIPECTL(0), hw.rd(DWC3_GUSB3PIPECTL(0)) & ~1u);

    // OEM UsbfnDwc3Dxe DwcInitialize (0x3b10..0x3b7c): partition TX FIFOs 1..15
    {
        uint32_t fifoAddr = hw.rd(DWC3_GTXFIFOSIZ(0)) & 0xFFFFu;
        for (unsigned ep = 1; ep <= 15; ++ep) {
            const uint32_t depth = (ep < 7u) ? 0x0184u : 0x0082u;
            hw.wr(DWC3_GTXFIFOSIZ(ep), (fifoAddr << 16) | depth);
            fifoAddr += depth;
        }
    }

    // Exact UsbfnDwc3Dxe GCTL sequence (0x3cf0..0x3d3c): clear bit 16 (U2RSTECN), PRTCAPDIR=2 (Device), PWRDNSCALE=2
    hw.wr(DWC3_GCTL, hw.rd(DWC3_GCTL) & ~0x00010000u);
    hw.wr(DWC3_GCTL, (hw.rd(DWC3_GCTL) & ~0x00003000u) | DWC3_GCTL_PRTCAPDIR(DWC3_GCTL_PRTCAP_DEVICE));
    hw.wr(DWC3_GCTL, (hw.rd(DWC3_GCTL) & 0x0007FFFFu) | 0x00100000u);

    // Exact UsbfnDwc3Dxe DCFG + DEVTEN + DEPSTARTCFG + Event Buffer order (0x3d44..0x40e0)
    hw.wr(DWC3_DCFG,
          (hw.rd(DWC3_DCFG) & ~(DWC3_DCFG_SPEED_MASK | DWC3_DCFG_DEVADDR_MASK)) |
          (1u << 22) | DWC3_DCFG_HIGHSPEED);
    hw.wr(DWC3_DEVTEN, 0x07u);       // DISCONNEVTEN | USBRSTEN | CONNECTDONEEN

    // UsbfnDwc3Dxe 0x3dfc..0x3e58 issues DEPSTARTCFG(0) before programming GEVNTADR/SIZ/COUNT
    (void)epCmd(hw, 0, DWC3_DEPCMD_DEPSTARTCFG, 0, 0, 0);

    const uint64_t evtPa = hw.dmaPhys + DMA_EVT_OFF;
    hw.wr(DWC3_GEVNTADRLO(0), static_cast<uint32_t>(evtPa));
    hw.wr(DWC3_GEVNTADRHI(0), static_cast<uint32_t>(evtPa >> 32));
    hw.wr(DWC3_GEVNTSIZ(0), 4096u);  // bit 31 clear: event generation unmasked
    hw.wr(DWC3_GEVNTCOUNT(0), 0u);
    hw.evtOff = 0u;

    programEp0(hw);

    // Hold SE0 disconnect cleanly for 30ms before asserting D+ pull-up via RUN_STOP (0x6480..0x64ac)
    IOSleep(30);
    hw.wr(DWC3_DCTL, hw.rd(DWC3_DCTL) | DWC3_DCTL_RUN_STOP);
    {
        char msg[128];
        snprintf(msg, sizeof(msg),
                 "usb: DWC3 CDC-ACM running gsnpsid=0x%08x dsts=0x%08x qss=0x%08x",
                 gsnpsid, hw.rd(DWC3_DSTS), hw.rd(QSCRATCH_SS_PHY_CTRL));
        logStage(msg);
    }
    return true;
}

__attribute__((unused)) static TerminalSession *gSession = nullptr;

static void usbDebugThread(void *arg, int waitResult) {
    (void)arg;
    (void)waitResult;
    IOSleep(200);
    logStage("usb: debug thread started");

    void *rawMem = IOMalloc(sizeof(TerminalSession));
    if (!rawMem) return;
    memset(rawMem, 0, sizeof(TerminalSession));
    TerminalSession *s = new (rawMem, UsbPlaceTag{}) TerminalSession();
    s->hw.initDefaults();

    const uint32_t kReplyBytes = 3u * 1024u * 1024u;
    const uint32_t kRgbBytes   = 2u * 1024u * 1024u;
    s->replyMem = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, kIODirectionInOut, kReplyBytes, 4096);
    s->rgbMem   = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, kIODirectionInOut, kRgbBytes, 4096);
    if (!s->replyMem || !s->rgbMem ||
        s->replyMem->prepare() != kIOReturnSuccess ||
        s->rgbMem->prepare() != kIOReturnSuccess) {
        logStage("usb: reply/rgb buffer alloc failed");
        return;
    }

    s->reply.buf = static_cast<uint8_t *>(s->replyMem->getBytesNoCopy());
    s->reply.cap = kReplyBytes;
    s->reply.reset();
    s->screen.init(static_cast<uint8_t *>(s->rgbMem->getBytesNoCopy()), kRgbBytes);
    s->ramoops = reinterpret_cast<volatile const uint8_t *>(
        mapRangeUncached(J716F_RAMOOPS_BASE, J716F_RAMOOPS_SIZE, s->ramoopsMap));

    if (!bringUpController(*s)) return;
    gSession = s;

    uint8_t *txScratch = static_cast<uint8_t *>(IOMalloc(DMA_EP3_MAX_CHUNK));
    if (!txScratch) return;
    gFlushScratch = txScratch;

    uint64_t bootTick = nowMs();
    uint64_t hudTick  = 0;
    unsigned replugs  = 0;

    for (;;) {
        pollUsbEvents(*s);

        const uint64_t now = nowMs();
        if (now >= hudTick) {
            hudTick = now + 250ULL;
            const uint32_t dsts = s->hw.rd(DWC3_DSTS);
            const uint32_t dctl = s->hw.rd(DWC3_DCTL);
            const uint32_t gctl = s->hw.rd(DWC3_GCTL);
            const uint32_t qcfg = s->hw.rd(QSCRATCH_GENERAL_CFG);
            const uint32_t qhs  = s->hw.rd(QSCRATCH_HS_PHY_CTRL);
            const uint32_t pclk = s->hw.grd(GCC_USB3_PRIM_PHY_PIPE_CLK);
            const uint32_t gcnt = s->hw.rd(DWC3_GEVNTCOUNT(0));
            snprintf(gUsbHudLine0, sizeof(gUsbHudLine0),
                     "USB: ev=%u rst=%u cfg=%u ep0=%d cmd=%d phy=%u smmu=%u(smr=%08x/%02x) rplg=%u",
                     s->hw.usbEvents, s->hw.usbResets, s->hw.configured,
                     s->hw.ep0Stage, s->hw.lastCmdSt, s->hw.phyInitMode,
                     s->hw.smmuBank, s->hw.smmuOrigSmr, s->hw.smmuOrigS2cr & 0xFFu, replugs);
            snprintf(gUsbHudLine1, sizeof(gUsbHudLine1),
                     "REG: dsts=%08x dctl=%08x gctl=%08x qcfg=%08x qhs=%08x pclk=%08x gcnt=%u",
                     dsts, dctl, gctl, qcfg, qhs, pclk, gcnt);
            renderHudOverlay();
            snprintf(ruan_usb_short, sizeof(ruan_usb_short), "usb%s e%u r%u c%u%s d%x", s->hw.dmaDesc ? "" : "A",   // A: DMA from the reserved arena
                     s->hw.usbEvents, s->hw.usbResets, s->hw.configured, s->hw.hostReady ? "o" : "", dsts);
        }
        if (s->hw.ep3Busy && now > s->hw.ep3ArmTick + 2000ULL) {
            endDepTransfer(s->hw, 3, s->hw.ep3RscIdx, s->hw.ep3Busy);
        }

        // Fallback Stage 1 at t+4s: if no events arrived on UEFI-preserved PHY state,
        // run full Femto v2 HS PHY re-init + glitch-free QSCRATCH UTMI clock mux + DwcInitialize!
        if (replugs == 0 && s->hw.usbEvents == 0 && now > bootTick + 4000ULL) {
            ++replugs;
            s->hw.phyInitMode = 1u;
            s->hw.wr(DWC3_DCTL, s->hw.rd(DWC3_DCTL) & ~DWC3_DCTL_RUN_STOP);
            IOSleep(50);
            (void)bringUpController(*s);
            logStage("usb: fallback Femto v2 HS PHY + UTMI mux replug issued");
        }

        if (s->hw.configured && s->hw.hostReady) {
            if (s->hw.needReplay) {
                s->hw.needReplay = false;
                replayRamoops(*s, true);
            }
            if (s->screen.streaming && s->reply.used == 0 && now >= s->screen.nextFrameTick) {
                const uint32_t interval = 1000u / (s->screen.maxFps ? s->screen.maxFps : 1u);
                s->screen.nextFrameTick = now + interval;
                (void)usbCaptureAndQueueGsc1(s->screen, s->reply, false);
            }
            if (s->xfer.active) usbFilePump(s->xfer, s->reply);
            if (!s->hw.ep3Busy) {
                if (s->reply.used > 0) {
                    const uint32_t n = s->reply.pop(txScratch, DMA_EP3_MAX_CHUNK);
                    (void)startBulkIn(s->hw, txScratch, n);
                } else if (s->ramoops) {
                    volatile const uint32_t *hdr = reinterpret_cast<volatile const uint32_t *>(s->ramoops);
                    const uint32_t sig = hdr[0], start = hdr[1];
                    if (sig == J716F_RAMOOPS_SIG && start < J716F_RAMOOPS_DATA && start != s->lastRamoopsPos) {
                        const volatile uint8_t *ring = s->ramoops + J716F_RAMOOPS_HEAD;
                        uint32_t avail = (start >= s->lastRamoopsPos)
                            ? (start - s->lastRamoopsPos)
                            : (J716F_RAMOOPS_DATA - s->lastRamoopsPos);
                        if (avail > DMA_EP3_MAX_CHUNK) avail = DMA_EP3_MAX_CHUNK;
                        for (uint32_t i = 0; i < avail; ++i) {
                            txScratch[i] = ring[s->lastRamoopsPos + i];
                        }
                        if (startBulkIn(s->hw, txScratch, avail)) {
                            s->lastRamoopsPos = (s->lastRamoopsPos + avail) % J716F_RAMOOPS_DATA;
                        }
                    }
                }
            }
        }

        usbGpuPump(s);

        if (s->pendingFastboot && (!s->hw.configured || !s->hw.hostReady || (s->reply.used == 0 && !s->hw.ep3Busy))) {
            IOSleep(50);
            executeWarmFastbootReboot(s->hw);
        }

        if (!s->hw.configured) {
            IODelay(200);  // fast poll (~0.2ms) during USB enumeration
        } else if (s->hw.ep3Busy || s->reply.used > 0 || s->screen.streaming) {
            IOSleep(1);
        } else {
            IOSleep(5);
        }
    }
}

} // namespace

extern "C" void usb_debug_draw_hud(void) {
    renderHudOverlay();
}

extern "C" void native_usb_debug_probe(void) {
    static int started = 0;
    if (__atomic_exchange_n(&started, 1, __ATOMIC_ACQ_REL)) return;
    unsigned enable = 0;
    (void)PE_parse_boot_argn("ruan-usbdbg", &enable, sizeof(enable));
    if (!enable) return;
    strlcpy(ruan_usb_short, "usb: starting", sizeof(ruan_usb_short));
    thread_t th = nullptr;
    if (kernel_thread_start(usbDebugThread, nullptr, &th) == KERN_SUCCESS && th) {
        thread_deallocate(th);
    }
}

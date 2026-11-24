// SPDX-License-Identifier: BSD-2-Clause-Patent
// RuanBacklight: AppleARMBacklight conformance & IODisplayParameters service for ruan (Silergy SY7758 over I2C).
// CoreBrightness (backboardd) finds a service with backlight-control = true that publishes IODisplayParameters brightness,
// and sets {brightness, FadePeriod (16.16 s)} through setProperties.
#include "RuanBacklight.h"
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSString.h>
#include <libkern/c++/OSBoolean.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include <mach/mach_time.h>

extern "C" {
    vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
}

/* The backlight is a Silergy SY7758 on I2C, not a panel DCS command: the live DT has the panel at
 * bl_ctrl_external, WLED and LPG disabled, and sy7758@2e (compatible "sy,sy7758") on i2c@984000 = QUP0 SE1,
 * clock GCC_QUPV3_WRAP0_S1_CLK (id 64). Brightness is 12 bits in REG 0x10 (bits 7:0) and 0x11 (bits 3:0)
 * (Linux drivers/video/backlight/sy7758.c). The bootloader already powered and configured the chip and the
 * I2C engine; we only check that, then write the two brightness registers. Nothing else on the chip is touched. */
#define GCC_PHYS            0x00100000ULL
#define GCC_SIZE            0x40000ULL
#define SE_PHYS             0x00984000ULL   /* i2c@984000 */
#define SE_SIZE             0x4000ULL
#define SY7758_ADDR         0x2e
#define SY7758_DEV_CTL      0x01   /* bit 7 fast, bits 2:1 brightness mode (Linux sets 2 = from the I2C register), bit 0 BL_CTLB */
#define SY7758_DEV_ID       0x03
#define SY7758_BRT_L        0x10
#define SY7758_BRT_H        0x11
#define CLK_OFF             (1u << 31)       /* CBCR bit 31: the branch clock is not running */
/* gcc-parrot.c halt registers: wrap0 S1, wrap0 M/S AHB, wrap0 core (all must run before the SE is touched) */
static const uint32_t kGccCbcr[] = {0x27140, 0x27004, 0x27008, 0x33000};

/* GENI registers (qcom-geni-se.h, i2c-qcom-geni.c) */
enum : uint32_t {
    GENI_STATUS = 0x040, GENI_SER_M_CLK_CFG = 0x048, GENI_FW_REVISION_RO = 0x068, GENI_DMA_MODE_EN = 0x258,
    GENI_TX_PACKING_CFG0 = 0x260, GENI_TX_PACKING_CFG1 = 0x264, I2C_TX_TRANS_LEN = 0x26c, I2C_RX_TRANS_LEN = 0x270,
    I2C_SCL_COUNTERS = 0x278, GENI_RX_PACKING_CFG0 = 0x284, GENI_RX_PACKING_CFG1 = 0x288, GENI_M_CMD0 = 0x600,
    GENI_M_CMD_CTRL = 0x604, GENI_M_IRQ_STATUS = 0x610, GENI_M_IRQ_EN = 0x614, GENI_M_IRQ_CLEAR = 0x618,
    GENI_TX_FIFO = 0x700, GENI_RX_FIFO = 0x780, GENI_RX_FIFO_STATUS = 0x804, SE_IRQ_EN = 0xe1c,
};
enum : uint32_t {
    M_CMD_DONE = 1u << 0, M_CMD_CANCEL = 1u << 4, M_CMD_ABORT = 1u << 5,
    /* SE_I2C_ERR: overrun 1, illegal 2, failure 3, GP1 = NACK 10, GP3 = bus protocol 12, GP4 = arbitration 13 */
    M_I2C_ERRORS = (1u << 1) | (1u << 2) | (1u << 3) | (1u << 5) | (1u << 10) | (1u << 12) | (1u << 13),
    I2C_WRITE = 1u << 27, I2C_READ = 2u << 27, STOP_STRETCH = 1u << 2, PROTO_I2C = 3,
};

struct ruan_backlight_state g_ruan_backlight = {
    .current_level = 0, .max_level = 4095, .min_level = 16, .ready = false, .dev_id = 0, .last_irq = 0,
    .updates_count = 0, .errors = 0, .status = "not started",
};

namespace {
constexpr uint32_t kMaxLevel = 4095, kStepMs = 16;
volatile uint64_t gRequest = 0;
} // namespace

static vm_offset_t s_se = 0;
static uint32_t s_hw_max = 1600;   /* chip level for iPadOS full brightness (boot-arg ruan-bl-max, 16..4095) */
static IOLock *s_lock = nullptr;
/* ruan-bl-svc=1: the non-blocking service in RuanBacklightSvc.cpp drives the chip; the calls below hand over to it. */
static bool s_svc = false;
extern "C" bool ruan_bl_svc_start(volatile uint32_t *se);
extern "C" int ruan_bl_svc_set_level(uint32_t level);
extern "C" int ruan_bl_svc_reg(uint8_t reg, int value);

static inline uint32_t se_rd(uint32_t off) { return *(volatile uint32_t *)(s_se + off); }
static inline void se_wr(uint32_t off, uint32_t v) { *(volatile uint32_t *)(s_se + off) = v; __asm__ volatile("dsb sy" ::: "memory"); }

static void geni_recover(void) {
    se_wr(GENI_M_CMD_CTRL, 1u << 2);   /* cancel, then abort if cancel does not finish (as RuanTouch) */
    for (int i = 0; i < 1000 && !(se_rd(GENI_M_IRQ_STATUS) & M_CMD_CANCEL); i++) IODelay(10);
    if (!(se_rd(GENI_M_IRQ_STATUS) & M_CMD_CANCEL)) {
        se_wr(GENI_M_CMD_CTRL, 1u << 1);
        for (int i = 0; i < 1000 && !(se_rd(GENI_M_IRQ_STATUS) & M_CMD_ABORT); i++) IODelay(10);
    }
    for (int i = 0; i < 16 && (se_rd(GENI_RX_FIFO_STATUS) & 0x01ffffff); i++) (void)se_rd(GENI_RX_FIFO);
    se_wr(GENI_M_IRQ_CLEAR, 0xffffffff);
}

/* One I2C command in FIFO mode: write `n` bytes (n <= 4) or read one byte. 0, or the M_IRQ status that failed. */
static uint32_t geni_i2c(uint32_t op, const uint8_t *tx, uint32_t n, uint8_t *rx, uint32_t params) {
    for (int i = 0; se_rd(GENI_STATUS) & 1; i++) {   /* a previous command still running */
        if (i > 200) { geni_recover(); break; }
        IODelay(50);
    }
    se_wr(GENI_M_IRQ_CLEAR, 0xffffffff);
    if (op == I2C_WRITE) se_wr(I2C_TX_TRANS_LEN, n);
    else se_wr(I2C_RX_TRANS_LEN, 1);
    se_wr(GENI_M_CMD0, op | ((uint32_t)SY7758_ADDR << 9) | params);
    if (op == I2C_WRITE) {
        uint32_t word = 0;
        for (uint32_t i = 0; i < n; i++) word |= (uint32_t)tx[i] << (8 * i);
        se_wr(GENI_TX_FIFO, word);
    }
    uint64_t deadline;
    clock_interval_to_deadline(20, NSEC_PER_MSEC, &deadline);
    uint32_t st = 0;
    while (mach_absolute_time() < deadline) {
        st = se_rd(GENI_M_IRQ_STATUS);
        if (st & M_I2C_ERRORS) break;
        if (st & M_CMD_DONE) {
            if (rx) {
                if (!(se_rd(GENI_RX_FIFO_STATUS) & 0x01ffffff)) break;
                *rx = (uint8_t)se_rd(GENI_RX_FIFO);
            }
            se_wr(GENI_M_IRQ_CLEAR, st);
            return 0;
        }
    }
    g_ruan_backlight.last_irq = st ? st : 0xffffffffu;   /* all ones = timed out with no status at all */
    g_ruan_backlight.errors++;
    geni_recover();
    return g_ruan_backlight.last_irq;
}

static uint32_t sy7758_write(uint8_t reg, uint8_t value) {
    const uint8_t b[2] = {reg, value};
    return geni_i2c(I2C_WRITE, b, 2, nullptr, 0);
}

static uint32_t sy7758_read(uint8_t reg, uint8_t *value) {
    uint32_t e = geni_i2c(I2C_WRITE, &reg, 1, nullptr, STOP_STRETCH);   /* register address, repeated start */
    return e ? e : geni_i2c(I2C_READ, nullptr, 0, value, 0);
}

extern "C" {

/* Read-only checks first: every clock running, then the engine holds I2C firmware; only then is the SE touched
 * (reading a clock-gated QUP block can bus-fault and reset the tablet, as LPASS did). */
/* Every QUP0 clock running, then the SE mapped and holding I2C firmware; false (status says why) leaves the SE untouched. */
static bool map_checked_se(void) {
    if (!s_lock) s_lock = IOLockAlloc();
    vm_offset_t gcc = ml_io_map((vm_offset_t)GCC_PHYS, (vm_size_t)GCC_SIZE);
    if (!gcc || !s_lock) { strlcpy(g_ruan_backlight.status, "map/lock failed", sizeof g_ruan_backlight.status); return false; }
    for (uint32_t off : kGccCbcr) {
        const uint32_t cbcr = *(volatile uint32_t *)(gcc + off);
        if (cbcr & CLK_OFF) {
            snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status, "QUP0 clock off (GCC+%#x = %08x); SE not touched", off, cbcr);
            IOLog("ruan-backlight: %s\n", g_ruan_backlight.status);
            return false;
        }
    }
    s_se = ml_io_map((vm_offset_t)SE_PHYS, (vm_size_t)SE_SIZE);
    if (!s_se) { strlcpy(g_ruan_backlight.status, "SE map failed", sizeof g_ruan_backlight.status); return false; }
    const uint32_t proto = (se_rd(GENI_FW_REVISION_RO) >> 8) & 0xff;
    if (proto != PROTO_I2C) {
        snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status, "SE protocol %u, not I2C", proto);
        IOLog("ruan-backlight: %s\n", g_ruan_backlight.status);
        return false;
    }
    return true;
}

void ruan_backlight_init(void) {
    if (g_ruan_backlight.ready || s_se) return;
    if (!map_checked_se()) return;
    const uint32_t clk_cfg = se_rd(GENI_SER_M_CLK_CFG), scl = se_rd(I2C_SCL_COUNTERS);
    /* FIFO mode, polled status bits (the interrupt stays masked at the GIC), byte packing as Linux I2C (8 bits,
     * 4 per FIFO word, the same values RuanTouch uses). Clock divider and SCL timing stay as the bootloader set them. */
    se_wr(GENI_DMA_MODE_EN, se_rd(GENI_DMA_MODE_EN) & ~1u);
    se_wr(SE_IRQ_EN, se_rd(SE_IRQ_EN) | 0xf);
    se_wr(GENI_M_IRQ_EN, se_rd(GENI_M_IRQ_EN) | 0x7fc07e7f);
    se_wr(GENI_TX_PACKING_CFG0, 0x0007f8fe);
    se_wr(GENI_TX_PACKING_CFG1, 0x000ffefe);
    se_wr(GENI_RX_PACKING_CFG0, 0x0007f8fe);
    se_wr(GENI_RX_PACKING_CFG1, 0x000ffefe);

    uint8_t id = 0, lo = 0, hi = 0;
    IOLockLock(s_lock);
    uint32_t e = sy7758_read(SY7758_DEV_ID, &id);
    if (!e) e = sy7758_read(SY7758_BRT_L, &lo);
    if (!e) e = sy7758_read(SY7758_BRT_H, &hi);
    IOLockUnlock(s_lock);
    if (e) {
        snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status,
            "SY7758 read failed (m_irq %08x, clk_cfg %08x, scl %08x)", e, clk_cfg, scl);
        IOLog("ruan-backlight: %s\n", g_ruan_backlight.status);
        return;
    }
    g_ruan_backlight.dev_id = id;
    const uint32_t boot_level = (uint32_t)lo | ((uint32_t)(hi & 0x0f) << 8);
    uint32_t cap = 0;
    if (PE_parse_boot_argn("ruan-bl-max", &cap, sizeof cap) && cap >= 16 && cap <= 4095) s_hw_max = cap;
    g_ruan_backlight.ready = true;
    /* start dim (25% of the cap) until iPadOS sets its own value, which is then scaled into the cap too */
    const int rc = ruan_backlight_set_level(g_ruan_backlight.max_level / 4);
    /* The bootloader leaves the chip taking brightness from the panel's PWM, so the register writes above change
     * nothing on screen. Switch to register mode (bits 2:1 = 2, as Linux sy7758_init) after the level is in place,
     * keeping the other bits as the bootloader set them. */
    uint8_t ctl = 0, ctl_after = 0;
    IOLockLock(s_lock);
    uint32_t ce = sy7758_read(SY7758_DEV_CTL, &ctl);
    if (!ce && ((ctl >> 1) & 3) != 2) ce = sy7758_write(SY7758_DEV_CTL, (uint8_t)((ctl & ~0x06u) | (2u << 1)));
    if (!ce) ce = sy7758_read(SY7758_DEV_CTL, &ctl_after);
    IOLockUnlock(s_lock);
    snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status,
        "SY7758 ok: id %02x, bootloader level %u, cap %u, start rc %d, dev_ctl %02x->%02x%s", id, boot_level, s_hw_max, rc,
        ctl, ctl_after, ce ? " (dev_ctl i2c error)" : "");
    IOLog("ruan-backlight: %s\n", g_ruan_backlight.status);
}

int ruan_backlight_set_level(uint32_t level) {
    if (s_svc) return ruan_bl_svc_set_level(level);
    if (!g_ruan_backlight.ready) return -1;
    if (level > g_ruan_backlight.max_level) level = g_ruan_backlight.max_level;
    uint32_t hw = (uint32_t)(((uint64_t)level * s_hw_max) / g_ruan_backlight.max_level);   /* iPadOS units -> chip */
    if (hw < g_ruan_backlight.min_level) hw = g_ruan_backlight.min_level;   /* never fully dark: no way back */
    IOLockLock(s_lock);
    uint32_t e = sy7758_write(SY7758_BRT_L, (uint8_t)(hw & 0xff));   /* low then high, as sy7758.c */
    if (!e) e = sy7758_write(SY7758_BRT_H, (uint8_t)((hw >> 8) & 0x0f));
    uint8_t lo = 0, hi = 0;   /* read back, so a successful return means the chip really holds the level */
    if (!e) e = sy7758_read(SY7758_BRT_L, &lo);
    if (!e) e = sy7758_read(SY7758_BRT_H, &hi);
    IOLockUnlock(s_lock);
    if (e) return -5;
    if (((uint32_t)lo | ((uint32_t)(hi & 0x0f) << 8)) != hw) {
        g_ruan_backlight.errors++;
        return -6;
    }
    g_ruan_backlight.current_level = level;
    g_ruan_backlight.updates_count++;
    return 0;
}

/* USB debug: read (value < 0) or write one SY7758 register; returns the value read back, or -1 on an I2C error. */
int ruan_backlight_reg(uint8_t reg, int value) {
    if (s_svc) return ruan_bl_svc_reg(reg, value);
    if (!g_ruan_backlight.ready) return -1;
    uint8_t v = 0;
    IOLockLock(s_lock);
    uint32_t e = value >= 0 ? sy7758_write(reg, (uint8_t)value) : 0;
    if (!e) e = sy7758_read(reg, &v);
    IOLockUnlock(s_lock);
    return e ? -1 : v;
}

uint32_t ruan_backlight_get_level(void) {
    return g_ruan_backlight.current_level;
}

} // extern "C"

void RuanBacklight::setLevel(uint32_t value) {
    ruan_backlight_set_level(value);
}

void RuanBacklight::fadeStep(OSObject *owner, IOTimerEventSource *sender) {
    RuanBacklight *self = static_cast<RuanBacklight *>(owner);
    if (!self) return;

    const uint64_t elapsed = mach_absolute_time() - self->m_start;
    uint32_t next = self->m_to;
    if (elapsed < self->m_period && self->m_period > 0) {
        next = (uint32_t)((int64_t)self->m_from + ((int64_t)self->m_to - (int64_t)self->m_from) * (int64_t)elapsed / (int64_t)self->m_period);
    }
    if (!next && self->m_to) next = 1;
    if (next != self->m_level) {
        self->setLevel(next);
        self->m_level = next;
    }
    if (next != self->m_to && sender) {
        sender->setTimeoutMS(kStepMs);
    }
}

void RuanBacklight::beginFade(uint32_t goal, uint32_t milliseconds) {
    if (m_fade) m_fade->cancelTimeout();
    m_from = m_level;
    m_to = goal;
    m_start = mach_absolute_time();
    nanoseconds_to_absolutetime((uint64_t)milliseconds * NSEC_PER_MSEC, &m_period);
    fadeStep(this, m_fade);
}

void RuanBacklight::requestFired(OSObject *owner, IOTimerEventSource *) {
    RuanBacklight *self = static_cast<RuanBacklight *>(owner);
    if (!self) return;

    const uint64_t taken = __atomic_exchange_n(&gRequest, 0ull, __ATOMIC_ACQUIRE);
    if (taken >> 63) {
        self->beginFade((uint32_t)(taken >> 16) & 0xffff, (uint32_t)taken & 0xffff);
    }
}

void RuanBacklight::publish(uint32_t value) {
    OSDictionary *brightness = OSDictionary::withCapacity(3);
    OSDictionary *parameters = OSDictionary::withCapacity(1);
    OSNumber *min = OSNumber::withNumber(0ULL, 32);
    OSNumber *max = OSNumber::withNumber(kMaxLevel, 32);
    OSNumber *current = OSNumber::withNumber(value, 32);

    if (brightness && parameters && min && max && current) {
        brightness->setObject("min", min);
        brightness->setObject("max", max);
        brightness->setObject("value", current);
        parameters->setObject("brightness", brightness);
        setProperty("IODisplayParameters", parameters);
    }
    OSSafeReleaseNULL(min);
    OSSafeReleaseNULL(max);
    OSSafeReleaseNULL(current);
    OSSafeReleaseNULL(brightness);
    OSSafeReleaseNULL(parameters);
}

bool RuanBacklight::init(OSDictionary *propTable) {
    if (!IOService::init(propTable)) return false;
    m_level = m_to = kMaxLevel / 2;
    m_from = 0;
    m_start = m_period = 0;
    return true;
}

bool RuanBacklight::start(IOService *provider) {
    if (!IOService::start(provider)) return false;

    ruan_backlight_init();
    if (g_ruan_backlight.ready) m_level = m_to = g_ruan_backlight.current_level;

    m_loop = IOWorkLoop::workLoop();
    m_fade = IOTimerEventSource::timerEventSource(this, &RuanBacklight::fadeStep);
    m_request = IOTimerEventSource::timerEventSource(this, &RuanBacklight::requestFired);

    if (!m_loop || !m_fade || !m_request) return false;
    if (m_loop->addEventSource(m_fade) || m_loop->addEventSource(m_request)) return false;

    setProperty("NativeSandboxGrantProcess", "backboardd");
    setProperty("backlight-control", kOSBooleanTrue);

    publish(m_level);
    return true;
}

void RuanBacklight::stop(IOService *provider) {
    if (m_fade) {
        m_fade->cancelTimeout();
        if (m_loop) m_loop->removeEventSource(m_fade);
        OSSafeReleaseNULL(m_fade);
    }
    if (m_request) {
        m_request->cancelTimeout();
        if (m_loop) m_loop->removeEventSource(m_request);
        OSSafeReleaseNULL(m_request);
    }
    OSSafeReleaseNULL(m_loop);
    IOService::stop(provider);
}

IOReturn RuanBacklight::setProperties(OSObject *properties) {
    OSDictionary *dictionary = OSDynamicCast(OSDictionary, properties);
    if (!dictionary) return kIOReturnBadArgument;

    OSNumber *brightness = OSDynamicCast(OSNumber, dictionary->getObject("brightness"));
    if (!brightness) return kIOReturnSuccess;

    OSNumber *fadePeriod = OSDynamicCast(OSNumber, dictionary->getObject("FadePeriod"));
    const int32_t requested = (int32_t)brightness->unsigned32BitValue();
    const uint32_t goal = requested < 0 ? 0 : (uint32_t)requested > kMaxLevel ? kMaxLevel : (uint32_t)requested;
    uint64_t milliseconds = fadePeriod ? ((uint64_t)fadePeriod->unsigned32BitValue() * 1000) >> 16 : 0;
    if (milliseconds > 5000) milliseconds = 5000;

    __atomic_store_n(&gRequest, 1ull << 63 | (uint64_t)goal << 16 | milliseconds, __ATOMIC_RELEASE);
    if (m_request) m_request->setTimeoutUS(1);
    publish(goal);
    return kIOReturnSuccess;
}

static RuanBacklight *s_backlight = nullptr;

#include <libkern/OSKextLib.h>
#include <mach/kmod.h>
extern kmod_info_t g_kernel_kmod_info;
/* RuanBacklightSvc.cpp's static initializer, taken out of __mod_init_func by build-ram-root-probe.py (sheng's BacklightProbe.cpp). */
extern "C" void ruan_bl_svc_static_init(void) __asm__("__GLOBAL__sub_I_RuanBacklightSvc.cpp");

/* ruan-bl-svc=1: register RuanBacklightSvc's class with the kernel's module, then start it on the checked SE. */
/* The second SY7758 (ruan has two, one per half of the LED strings, both at 0x2e): i2c@990000 = QUP0 SE4 (live DT line 15668,
 * GIC SPI 605). Without it the strings it drives stay at the boot loader's level and that part of the panel cannot be dimmed or
 * brightened (rbu170p). Polled writes after the same read-only checks as the first chip: wrap0 S4 halt 0x274dc (gcc-parrot.c),
 * the wrap0 AHB and core clocks, then I2C firmware in the engine. ruan-bl-mirror=0 leaves it alone. */
#define SE2_PHYS 0x00990000ULL
static vm_offset_t s_se2 = 0;
static int s_mirror = -1;   /* -1 not tried, 0 unusable, 1 ready */
extern "C" char ruan_bl_mirror_status[96];
char ruan_bl_mirror_status[96] = "mirror: not tried";
static bool mirror_ready(void) {
    if (s_mirror >= 0) return s_mirror == 1;
    s_mirror = 0;
    unsigned on = 1;
    PE_parse_boot_argn("ruan-bl-mirror", &on, sizeof on);
    if (!on) { strlcpy(ruan_bl_mirror_status, "mirror: off (ruan-bl-mirror=0)", sizeof ruan_bl_mirror_status); return false; }
    if (!s_lock) s_lock = IOLockAlloc();
    vm_offset_t gcc = ml_io_map((vm_offset_t)GCC_PHYS, (vm_size_t)GCC_SIZE);
    if (!gcc || !s_lock) { strlcpy(ruan_bl_mirror_status, "mirror: map/lock failed", sizeof ruan_bl_mirror_status); return false; }
    static const uint32_t cbcr[] = {0x274dc, 0x27004, 0x27008, 0x33000};
    for (uint32_t off : cbcr) {
        const uint32_t v = *(volatile uint32_t *)(gcc + off);
        if (v & CLK_OFF) { snprintf(ruan_bl_mirror_status, sizeof ruan_bl_mirror_status, "mirror: clock off (GCC+%#x = %08x)", off, v); return false; }
    }
    s_se2 = ml_io_map((vm_offset_t)SE2_PHYS, (vm_size_t)SE_SIZE);
    if (!s_se2) { strlcpy(ruan_bl_mirror_status, "mirror: SE4 map failed", sizeof ruan_bl_mirror_status); return false; }
    const uint32_t proto = ((*(volatile uint32_t *)(s_se2 + GENI_FW_REVISION_RO)) >> 8) & 0xff;
    if (proto != PROTO_I2C) { snprintf(ruan_bl_mirror_status, sizeof ruan_bl_mirror_status, "mirror: SE4 protocol %u, not I2C", proto); return false; }
    IOLockLock(s_lock);
    const vm_offset_t saved = s_se; s_se = s_se2;
    se_wr(GENI_DMA_MODE_EN, se_rd(GENI_DMA_MODE_EN) & ~1u);
    se_wr(GENI_TX_PACKING_CFG0, 0x0007f8fe); se_wr(GENI_TX_PACKING_CFG1, 0x000ffefe);
    se_wr(GENI_RX_PACKING_CFG0, 0x0007f8fe); se_wr(GENI_RX_PACKING_CFG1, 0x000ffefe);
    uint8_t id = 0, ctl = 0;
    uint32_t e = sy7758_read(SY7758_DEV_ID, &id);
    if (!e) e = sy7758_read(SY7758_DEV_CTL, &ctl);
    if (!e) e = sy7758_write(SY7758_DEV_CTL, 0x80 | 0x01 | (2u << 1));   /* register mode, as the first chip (svc kDevCtlRegisterMode) */
    s_se = saved;
    IOLockUnlock(s_lock);
    if (e) { snprintf(ruan_bl_mirror_status, sizeof ruan_bl_mirror_status, "mirror: SY7758 #2 not answering (%08x)", e); return false; }
    snprintf(ruan_bl_mirror_status, sizeof ruan_bl_mirror_status, "mirror: SY7758 #2 id %02x, dev_ctl %02x -> 85", id, ctl);
    s_mirror = 1;
    return true;
}
/* The same chip level as the first SY7758 (called by RuanBacklightSvc.cpp as it writes its own). */
extern "C" void ruan_bl_mirror_level(uint32_t hw) {
    if (!mirror_ready()) return;
    IOLockLock(s_lock);
    const vm_offset_t saved = s_se; s_se = s_se2;
    uint32_t e = sy7758_write(SY7758_BRT_L, (uint8_t)(hw & 0xff));
    if (!e) e = sy7758_write(SY7758_BRT_H, (uint8_t)((hw >> 8) & 0x0f));
    s_se = saved;
    IOLockUnlock(s_lock);
    if (e) snprintf(ruan_bl_mirror_status, sizeof ruan_bl_mirror_status, "mirror: level %u write failed (%08x)", hw, e);
}

static bool ruan_bl_svc_probe(void) {
    if (!map_checked_se()) return false;
    void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if (!handle) { strlcpy(g_ruan_backlight.status, "svc: preModLoad failed", sizeof g_ruan_backlight.status); return false; }
    ruan_bl_svc_static_init();
    const OSReturn status = OSMetaClass::postModLoad(handle);
    if (status) { snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status, "svc: postModLoad %#x", status); return false; }
    s_svc = true;
    return ruan_bl_svc_start((volatile uint32_t *)s_se);
}

extern "C" bool ruan_backlight_start(void) {
    if (s_backlight || s_svc) return true;
    // Default on (rbu167p): the conforming service. This path sets backlight-control without AppleARMBacklight conformance, so
    // CoreBrightness never starts libEDR and QuartzCore's EDRGetDefaultMinScalingFactor waits out 5 s per frame (sheng int-236,
    // rbu114u-rbu166p: one frame every 5.0 s). ruan-bl-svc=0 gets this path back.
    unsigned svc = 1;
    PE_parse_boot_argn("ruan-bl-svc", &svc, sizeof svc);
    if (svc == 1) return ruan_bl_svc_probe();

    IOService *platform = IOService::getPlatform();
    if (!platform) return false;

    s_backlight = new RuanBacklight;
    if (!s_backlight || !s_backlight->init()) {
        OSSafeReleaseNULL(s_backlight);
        return false;
    }

    s_backlight->setName("AppleARMBacklight");
    if (!s_backlight->attach(platform)) {
        s_backlight->release();
        s_backlight = nullptr;
        return false;
    }
    if (!s_backlight->start(platform)) {
        s_backlight->detach(platform);
        s_backlight->release();
        s_backlight = nullptr;
        return false;
    }
    s_backlight->registerService();
    IOLog("ruan-backlight: RuanBacklight registered under platform\n");
    return true;
}

// SPDX-License-Identifier: BSD-2-Clause-Patent
// Non-blocking panel brightness for ruan (boot argument ruan-bl-svc=1, started by ruan_backlight_start in RuanBacklight.cpp).
// Copied from UniXNU-Dizi-Ruan package/AppleARMBacklight.cpp (sheng's ShengBacklight) and cut down to ruan's one engine: a Silergy SY7758
// at I2C address 0x2e on QUP0 SE1 (i2c@984000, GIC SPI 602 level, live DT), 12-bit level in BRT_L 0x10 (bits 7:0) and BRT_H 0x11 (bits 3:0).
// The engine runs the GENI I2C firmware the boot loader left loaded and clocked; RuanBacklight.cpp's clock checks run first (a gated
// QUP block is never touched) and only FIFO transfers are issued, through the event-driven core in GeniI2c.c.
// Transfers never wait: the engine's interrupt only reads and clears its status, records it and signals the work loop, which advances the
// transfer. Until the interrupt is attached (retried every 250 ms) the work loop polls the status every millisecond while a transfer runs.
// A step that gets no answer within 25 ms is cancelled, then aborted. A newer level replaces one not yet written, so a fade never queues up.
// The class cannot be called AppleARMBacklight: AppleARMPlatform already defines that class and a duplicate name panics the kernel (rbu32,
// sheng int-229); the service answers user space's conformance query for it instead (impersonate, from publishFirst).
// CoreBrightness (backboardd) looks for a backlight service with backlight-control = true, reads min and max from IODisplayParameters
// brightness and sets {brightness, FadePeriod (16.16 seconds)} through setProperties, which only hands the request to the work loop.
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOInterruptEventSource.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSSymbol.h>
#include <pexpert/pexpert.h>
#include "GeniI2c.h"
#include "RuanBacklight.h"

// [0] stage (2 engine ready, 3 published, 4 published as AppleARMBacklight, negative: the step that failed), [1] brightness requests,
// [2] last hardware level written, [3] hardware level read back at start, [5] transfer errors, [6] last M_IRQ status of a failed
// transfer, [7] engine protocol and clock configuration (proto << 24 | M_CLK_CFG), [9] last error (GeniI2c.h error, or a setup code),
// [10] interrupts, [12] interrupt mode (0 polling, 1 attached, else the attach result), [13] transfer timeouts, [14] attach tries,
// [15] transfers done
extern "C" {volatile int32_t ruan_bl_svc_stats[16];}
extern "C" void ruan_bl_mirror_level(uint32_t);
extern "C" void ruan_screen_set(int);   // RuanInput.c: the display power state the governors and input threads follow
extern "C" int armcpu_spi_attach(uint32_t, bool, void (*)(void *), void *, uint32_t *, uint64_t *) __attribute__((weak_import));

namespace {
constexpr uint32_t kSpi = 602;   // i2c@984000 interrupts = <0 0x25a 4> (hardware/private/ruan-live.dts)
constexpr uint8_t kAddress = 0x2e, kDevCtl = 0x01, kDevId = 0x03, kBrtL = 0x10, kBrtH = 0x11;
// DEV_CTL: fast mode, BL_CTLB, brightness from the I2C registers (bits 2:1 = 2, Linux sy7758_init).
constexpr uint8_t kDevCtlRegisterMode = 0x80 | 0x01 | (2 << 1);
// iPadOS works in 0..kMaxLevel; the chip gets that scaled into [kFloor, ruan-bl-max]. The nits range sets the slider's scale only.
constexpr uint32_t kMinNits = 2, kMidNits = 140, kMaxNits = 500;
constexpr uint32_t kMaxLevel = 4095, kFloor = 16, kStepMs = 16, kPollMs = 1, kStepDeadlineMs = 25, kAttachMs = 250, kAttachTries = 240;

volatile uint32_t *gSe;
uint32_t gHwMax = 1600;
volatile uint32_t gIrqStatus;
IOInterruptEventSource *volatile gInbox;
// The newest brightness asked for: goal << 16 | fade milliseconds, with bit 63 set while the work loop has not taken it.
volatile uint64_t gRequest;
// USB debug register access, run by the work loop between brightness writes: reg | value << 8 | write << 16, bit 31 while pending.
volatile uint32_t gDebug;
volatile int32_t gDebugResult;

uint32_t rd(volatile uint32_t *base, uint32_t reg) {return base[reg / 4];}
void wr(volatile uint32_t *base, uint32_t reg, uint32_t value) {base[reg / 4] = value; __asm__ volatile("dsb sy" ::: "memory");}
uint32_t ioRead(void *ctx, uint32_t reg) {return rd(static_cast<volatile uint32_t *>(ctx), reg);}
void ioWrite(void *ctx, uint32_t reg, uint32_t value) {wr(static_cast<volatile uint32_t *>(ctx), reg, value);}
void bump(int index) {ruan_bl_svc_stats[index] = ruan_bl_svc_stats[index] + 1;}
uint32_t hwLevel(uint32_t level) {
    // 0 is CoreBrightness turning the display off (the power button): backlight off, else the boot console behind the stopped
    // scanout shows (rbu177). The slider's lowest step is 1, so every slider value keeps the floor and is never fully dark.
    if (level == 0) return 0;
    const uint32_t hw = (uint32_t)((uint64_t)level * gHwMax / kMaxLevel);
    return hw < kFloor ? kFloor : hw;
}

// Interrupt context: read and clear the engine's status, keep it for the work loop and signal it. Nothing else.
void seIrq(void *) {
    const uint32_t status = rd(gSe, GENI_M_IRQ_STATUS);
    // The TX watermark is a level (sheng int-279: cleared here alone it stormed): turned off here, the status bit still tells the work loop.
    if (status & GENI_M_TX_WATERMARK) wr(gSe, GENI_TX_WATERMARK, 0);
    if (status) wr(gSe, GENI_M_IRQ_CLEAR, status);
    __atomic_fetch_or(&gIrqStatus, status, __ATOMIC_RELEASE);
    bump(10);
    IOInterruptEventSource *inbox = gInbox;
    if (inbox && status) inbox->interruptOccurred(nullptr, nullptr, 0);
}
}  // namespace

class RuanBacklightSvc : public IOService {
    OSDeclareDefaultStructors(RuanBacklightSvc)
    enum Step : uint8_t {StepNone, StepReadId, StepReadLsb, StepReadMsb, StepWriteLsb, StepWriteMsb, StepWriteCtl, StepDebugWrite, StepDebugRead};
    GeniI2c bus = {};
    Step step = StepNone;
    bool started = false, ctlDone = false, published = false, irqMode = false;
    uint8_t lsb = 0;
    int32_t written = -1;   // hardware level the chip holds, -1 unknown
    uint32_t sending = 0, sendingLevel = 0, bootHw = 0;
    uint64_t deadline = 0;
    IOWorkLoop *loop = nullptr;
    IOTimerEventSource *fade = nullptr, *tick = nullptr, *attachTimer = nullptr, *request = nullptr;
    IOInterruptEventSource *inbox = nullptr;
    uint32_t level = 0, from = 0, to = 0, target = 0, attachTries = 0;
    uint64_t start = 0, period = 0;

    static uint64_t now() {return mach_absolute_time();}
    static uint64_t after(uint32_t ms) {uint64_t delta = 0; nanoseconds_to_absolutetime((uint64_t)ms * NSEC_PER_MSEC, &delta); return now() + delta;}

    // Starts the engine's next transfer when it is free: start reads, a debug access, the newest level, then register mode once.
    void kick() {
        if (geni_i2c_busy(&bus)) return;
        int rc = 0;
        const uint32_t debug = __atomic_load_n(&gDebug, __ATOMIC_ACQUIRE);
        if (!started) {step = StepReadId; rc = geni_i2c_start_read(&bus, kDevId);}
        else if (debug >> 31) {
            if (debug & (1u << 16)) {step = StepDebugWrite; rc = geni_i2c_start_write(&bus, (uint8_t)debug, (uint8_t)(debug >> 8));}
            else {step = StepDebugRead; rc = geni_i2c_start_read(&bus, (uint8_t)debug);}
            if (rc) debugDone(-1);
        }
        else if (!published) {step = StepNone; return;}
        else if (written != (int32_t)hwLevel(target)) {
            sendingLevel = target; sending = hwLevel(target); step = StepWriteLsb;
            ruan_bl_mirror_level(sending);   // the second SY7758 (RuanBacklight.cpp): the other half of the LED strings
            ruan_screen_set(target == 0);
            rc = geni_i2c_start_write(&bus, kBrtL, (uint8_t)(sending & 0xff));   // low then high, as sy7758.c
        }
        else if (!ctlDone) {step = StepWriteCtl; rc = geni_i2c_start_write(&bus, kDevCtl, kDevCtlRegisterMode);}
        else {step = StepNone; return;}
        if (rc) {step = StepNone; return;}
        deadline = after(kStepDeadlineMs);
    }
    static void debugDone(int32_t result) {
        __atomic_store_n(&gDebugResult, result, __ATOMIC_RELEASE);
        __atomic_store_n(&gDebug, 0u, __ATOMIC_RELEASE);
    }
    void noteFailure() {
        bump(5);
        ruan_bl_svc_stats[6] = (int32_t)bus.error_status;
        ruan_bl_svc_stats[9] = (int32_t)bus.error;
        ruan_bl_svc_stats[13] = (int32_t)bus.timeouts;
        g_ruan_backlight.errors++;
        g_ruan_backlight.last_irq = bus.error_status ? bus.error_status : 0xffffffffu;
    }
    // A transfer ended: the next step of the sequence.
    void finished(int result) {
        const bool ok = result == GeniDone;
        if (!ok) noteFailure();
        else bump(15);
        int rc = 0;
        switch (step) {
        case StepReadId:
            if (!ok) {fail(4, bus.error); started = true; step = StepNone; return;}   // the chip does not answer: never published
            g_ruan_backlight.dev_id = bus.data;
            rc = geni_i2c_start_read(&bus, kBrtL); step = StepReadLsb;
            break;
        case StepReadLsb:
            if (ok) {lsb = bus.data; rc = geni_i2c_start_read(&bus, kBrtH); step = StepReadMsb; break;}
            started = true;
            break;
        case StepReadMsb:
            started = true;
            if (ok) {bootHw = ((uint32_t)(bus.data & 0x0f) << 8) | lsb; ruan_bl_svc_stats[3] = (int32_t)bootHw;}
            break;
        case StepWriteLsb:
            if (ok) {rc = geni_i2c_start_write(&bus, kBrtH, (uint8_t)((sending >> 8) & 0x0f)); step = StepWriteMsb; break;}
            written = (int32_t)sending;  // given up: written again with the next level asked for
            break;
        case StepWriteMsb:
            written = (int32_t)sending;
            if (ok) {
                ruan_bl_svc_stats[2] = (int32_t)sending;
                g_ruan_backlight.current_level = sendingLevel;
                g_ruan_backlight.updates_count++;
            }
            break;
        case StepWriteCtl:
            ctlDone = true;
            snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status, "svc: SY7758 id %02x, boot level %u, cap %u, dev_ctl %02x %s, irq %d",
                     g_ruan_backlight.dev_id, bootHw, gHwMax, kDevCtlRegisterMode, ok ? "set" : "failed", (int)ruan_bl_svc_stats[12]);
            break;
        case StepDebugWrite:
            if (ok) {rc = geni_i2c_start_read(&bus, (uint8_t)gDebug); step = StepDebugRead; if (rc) debugDone(-1); break;}
            debugDone(-1);
            break;
        case StepDebugRead:
            debugDone(ok ? bus.data : -1);
            break;
        default:
            break;
        }
        if (rc) noteFailure();
        if (geni_i2c_busy(&bus)) {deadline = after(kStepDeadlineMs); return;}
        step = StepNone;
        if (!published && started && ruan_bl_svc_stats[0] > 0) publishFirst();
        kick();
    }
    void service() {
        uint32_t status = __atomic_exchange_n(&gIrqStatus, 0u, __ATOMIC_ACQUIRE);
        if (!irqMode) {
            const uint32_t direct = rd(gSe, GENI_M_IRQ_STATUS);
            if (direct) wr(gSe, GENI_M_IRQ_CLEAR, direct);
            status |= direct;
        }
        if (status && geni_i2c_busy(&bus)) {
            const int result = geni_i2c_event(&bus, status);
            if (result != GeniPending) finished(result);
        }
        if (geni_i2c_busy(&bus) && now() >= deadline) {
            const int result = geni_i2c_timeout(&bus);
            ruan_bl_svc_stats[13] = (int32_t)bus.timeouts;
            if (result != GeniPending) finished(result);
            else deadline = after(kStepDeadlineMs);
        }
        armTick();
    }
    void armTick() {
        if (!geni_i2c_busy(&bus)) {tick->cancelTimeout(); return;}
        if (!irqMode) {tick->setTimeoutMS(kPollMs); return;}
        tick->wakeAtTime((AbsoluteTime)deadline);
    }
    static void inboxFired(OSObject *owner, IOInterruptEventSource *, int) {
        if (RuanBacklightSvc *self = static_cast<RuanBacklightSvc *>(owner)) self->service();
    }
    // A brightness or debug request on the work loop (setProperties and the USB commands arm this timer at once).
    static void requestFired(OSObject *owner, IOTimerEventSource *) {
        RuanBacklightSvc *self = static_cast<RuanBacklightSvc *>(owner);
        if (!self) return;
        const uint64_t taken = __atomic_exchange_n(&gRequest, 0ull, __ATOMIC_ACQUIRE);
        if (taken >> 63) self->beginFade((uint32_t)(taken >> 16) & 0xffff, (uint32_t)taken & 0xffff);
        self->kick();
        self->armTick();
    }
    static void tickFired(OSObject *owner, IOTimerEventSource *) {
        if (RuanBacklightSvc *self = static_cast<RuanBacklightSvc *>(owner)) self->service();
    }
    // Attaching the line, retried while the GIC driver is not up yet; the engine keeps working by polling meanwhile.
    static void attachFired(OSObject *owner, IOTimerEventSource *sender) {
        RuanBacklightSvc *self = static_cast<RuanBacklightSvc *>(owner);   // see impersonate()
        if (!self || self->irqMode) return;
        if (!armcpu_spi_attach) {ruan_bl_svc_stats[12] = -1; return;}
        ruan_bl_svc_stats[14] = (int32_t)++self->attachTries;
        const int rc = armcpu_spi_attach(32 + kSpi, false, seIrq, nullptr, nullptr, nullptr);
        if (rc == kIOReturnNotReady && self->attachTries < kAttachTries) {sender->setTimeoutMS(kAttachMs); return;}
        if (rc) {ruan_bl_svc_stats[12] = rc; return;}
        self->irqMode = true;
        ruan_bl_svc_stats[12] = 1;
        self->service();
    }

    void setLevel(uint32_t value) {
        target = value;
        kick();
        armTick();
    }
    static void fadeStep(OSObject *owner, IOTimerEventSource *sender) {
        RuanBacklightSvc *self = static_cast<RuanBacklightSvc *>(owner);   // see impersonate()
        if (!self) return;
        const uint64_t elapsed = now() - self->start;
        uint32_t next = self->to;
        if (elapsed < self->period)
            next = (uint32_t)((int64_t)self->from + ((int64_t)self->to - (int64_t)self->from) * (int64_t)elapsed / (int64_t)self->period);
        if (next != self->level) {self->setLevel(next); self->level = next;}
        if (next != self->to) sender->setTimeoutMS(kStepMs);
    }
    // On the work loop: a fade from the level now shown to goal.
    void beginFade(uint32_t goal, uint32_t milliseconds) {
        fade->cancelTimeout();
        from = level;
        to = goal;
        start = now();
        nanoseconds_to_absolutetime((uint64_t)milliseconds * NSEC_PER_MSEC, &period);
        fadeStep(this, fade);
    }
    static IOReturn begin(OSObject *owner, void *, void *, void *, void *) {
        RuanBacklightSvc *self = static_cast<RuanBacklightSvc *>(owner);   // see impersonate()
        if (!self) return kIOReturnBadArgument;
        self->kick();
        self->armTick();
        self->attachTimer->setTimeoutMS(1);
        return kIOReturnSuccess;
    }
    static void fail(int stage, int error) {ruan_bl_svc_stats[9] = error; ruan_bl_svc_stats[0] = -stage;
        snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status, "svc: SY7758 not answering (error %d, m_irq %08x)", error,
                 g_ruan_backlight.last_irq);}
    void publish(uint32_t value) {
        OSDictionary *brightness = OSDictionary::withCapacity(3), *milliNits = OSDictionary::withCapacity(3), *parameters = OSDictionary::withCapacity(2);
        OSNumber *min = OSNumber::withNumber(0ULL, 32), *max = OSNumber::withNumber(kMaxLevel, 32), *current = OSNumber::withNumber(value, 32);
        OSNumber *minMilli = OSNumber::withNumber(kMinNits * 1000ULL, 32), *maxMilli = OSNumber::withNumber(kMaxNits * 1000ULL, 32);
        OSNumber *currentMilli = OSNumber::withNumber((uint64_t)value * kMaxNits * 1000 / kMaxLevel, 32);
        if (brightness && milliNits && parameters && min && max && current && minMilli && maxMilli && currentMilli) {
            brightness->setObject("min", min); brightness->setObject("max", max); brightness->setObject("value", current);
            milliNits->setObject("min", minMilli); milliNits->setObject("max", maxMilli); milliNits->setObject("value", currentMilli);
            parameters->setObject("brightness", brightness);
            parameters->setObject("BrightnessMilliNits", milliNits);
            setProperty("IODisplayParameters", parameters);
        }
        OSSafeReleaseNULL(min); OSSafeReleaseNULL(max); OSSafeReleaseNULL(current); OSSafeReleaseNULL(minMilli); OSSafeReleaseNULL(maxMilli);
        OSSafeReleaseNULL(currentMilli); OSSafeReleaseNULL(brightness); OSSafeReleaseNULL(milliNits); OSSafeReleaseNULL(parameters);
    }
    // CoreBrightness's Display.m fails without a marketing table (equally spaced slider samples, signed 16.16 nits) and calibration
    // parameters; LmaxProduct is 4 bytes of 16.16, LmidProduct and LminProduct plain numbers (sheng).
    void publishCalibration() {
        const int32_t table[] = {(int32_t)(kMinNits << 16), (int32_t)(kMidNits << 16), (int32_t)(kMaxNits << 16)};
        if (OSData *marketing = OSData::withBytes(table, sizeof table)) {
            setProperty("backlight-marketing-table", marketing);
            marketing->release();
        }
        if (OSData *value = OSData::withBytes(&table[2], sizeof table[2])) {
            setProperty("LmaxProduct", value);
            value->release();
        }
        const struct {const char *key; uint32_t nits;} products[] = {{"LminProduct", kMinNits}, {"LmidProduct", kMidNits}};
        for (const auto &product : products) {
            if (OSNumber *value = OSNumber::withNumber(product.nits, 32)) {
                setProperty(product.key, value);
                value->release();
            }
        }
        OSDictionary *calibration = OSDictionary::withCapacity(9);
        if (!calibration) return;
        const struct {const char *key; uint32_t nits;} fields[] = {{"lMinProduct", kMinNits}, {"lMidProduct", kMidNits}, {"lMaxProduct", kMaxNits},
                                                                   {"lMinPanel", kMinNits}, {"lMidPanel", kMidNits}, {"lMaxPanel", kMaxNits}};
        // CoreBrightness dereferences every calibration number (rbu169p: backboardd SIGSEGV in CFNumberGetValue from CoreBrightness
        // once the service conformed). The three current fields stay 0, as UniXNU's pclm10 T733 backlight publishes them.
        static const char *const kCurrentKeys[] = {"current-for-max-backlight", "current-for-mid-backlight", "hardware-max-current-limit"};
        for (const char *key : kCurrentKeys) {
            if (OSNumber *zero = OSNumber::withNumber(0ULL, 32)) {
                calibration->setObject(key, zero);
                zero->release();
            }
        }
        for (const auto &field : fields) {
            if (OSNumber *number = OSNumber::withNumber((uint64_t)field.nits << 16, 32)) {
                calibration->setObject(field.key, number);
                number->release();
            }
        }
        setProperty("backlight-calibration-parameters", calibration);
        calibration->release();
    }
    // The service presents itself as AppleARMBacklight (AppleARMPlatform's class, loaded but without a device here): its vtable is copied
    // and getMetaClass (slot 7) answers that metaclass. IOObjectConformsTo and the sandbox both go through it. OSDynamicCast to this class
    // no longer works, which is why the event source actions cast statically. No prelinked kext but AppleARMPlatform names the class
    // (kernel.json, 2026-11-17), and the service is never freed. Done only after the chip answered, right before registerService.
    static inline const OSMetaClass *gAppleClass = nullptr;
    static const OSMetaClass *appleMetaClass(const OSMetaClassBase *) {return gAppleClass;}
    bool impersonate() {
        enum {kSlots = 320, kGetMetaClass = 7};
        const OSSymbol *name = OSSymbol::withCString("AppleARMBacklight");
        gAppleClass = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
        OSSafeReleaseNULL(name);
        if (!gAppleClass) return false;
#if __has_feature(ptrauth_calls)
        gAppleClass = nullptr;   // arm64e needs sheng's getMetaClass override; ruan's kernel is arm64
        return false;
#else
        uintptr_t *copy = static_cast<uintptr_t *>(IOMalloc(kSlots * sizeof(uintptr_t)));
        if (!copy) return false;
        memcpy(copy, *reinterpret_cast<uintptr_t **>(this), kSlots * sizeof(uintptr_t));
        copy[kGetMetaClass] = reinterpret_cast<uintptr_t>(&appleMetaClass);
        __asm__ volatile("dmb ish" ::: "memory");
        *reinterpret_cast<uintptr_t **>(this) = copy;
        return true;
#endif
    }
    // The chip answered the start reads: publish what the panel shows now and let CoreBrightness find the service.
    void publishFirst() {
        published = true;
        const uint32_t boot = bootHw >= kFloor ? (uint32_t)((uint64_t)bootHw * kMaxLevel / gHwMax) : kMaxLevel / 4;
        level = to = target = boot > kMaxLevel ? kMaxLevel : boot;
        g_ruan_backlight.current_level = level;
        g_ruan_backlight.ready = true;
        // CoreBrightness takes the backlight for the built-in display only when IOObjectConformsTo(service, "AppleARMBacklight") holds; with
        // backlight-control but without it, QuartzCore's libEDR send blocks and the screen stops updating (sheng int-236). So both or neither.
        const bool impersonated = impersonate();
        if (impersonated) {setProperty("NativeSandboxGrantProcess", "backboardd"); setProperty("backlight-control", true);}
        publishCalibration();
        publish(level);
        registerService();
        ruan_bl_svc_stats[0] = impersonated ? 4 : 3;
        snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status, "svc: SY7758 id %02x, boot level %u, cap %u, %s",
                 g_ruan_backlight.dev_id, bootHw, gHwMax, impersonated ? "published as AppleARMBacklight" : "published, no conformance");
    }
public:
    bool startBacklight(volatile uint32_t *se) {
        loop = IOWorkLoop::workLoop();
        fade = IOTimerEventSource::timerEventSource(this, &RuanBacklightSvc::fadeStep);
        tick = IOTimerEventSource::timerEventSource(this, &RuanBacklightSvc::tickFired);
        attachTimer = IOTimerEventSource::timerEventSource(this, &RuanBacklightSvc::attachFired);
        inbox = IOInterruptEventSource::interruptEventSource(this, &RuanBacklightSvc::inboxFired);
        request = IOTimerEventSource::timerEventSource(this, &RuanBacklightSvc::requestFired);
        if (!loop || !fade || !tick || !attachTimer || !inbox || !request) return false;
        if (loop->addEventSource(fade) || loop->addEventSource(tick) || loop->addEventSource(attachTimer) || loop->addEventSource(inbox) ||
            loop->addEventSource(request)) return false;
        gSe = se;
        const GeniIo io = {ioRead, ioWrite, (void *)se};
        uint32_t config = 0;
        const int prepared = geni_i2c_prepare(&bus, &io, kAddress, &config);
        ruan_bl_svc_stats[7] = (int32_t)config;
        if (prepared) {
            snprintf(g_ruan_backlight.status, sizeof g_ruan_backlight.status, "svc: SE not usable (proto/clk %08x)", config);
            return false;
        }
        uint32_t cap = 0;
        if (PE_parse_boot_argn("ruan-bl-max", &cap, sizeof cap) && cap >= kFloor && cap <= kMaxLevel) gHwMax = cap;
        g_ruan_backlight.min_level = kFloor;
        gInbox = inbox;
        ruan_bl_svc_stats[0] = 2;
        loop->runAction(&RuanBacklightSvc::begin, this);
        return true;
    }
    void post() {request->setTimeoutUS(1);}
    IOReturn setProperties(OSObject *properties) override {
        OSDictionary *dictionary = OSDynamicCast(OSDictionary, properties);
        if (!dictionary) return kIOReturnBadArgument;
        OSNumber *brightness = OSDynamicCast(OSNumber, dictionary->getObject("brightness"));
        if (!brightness) return kIOReturnSuccess;
        OSNumber *fadePeriod = OSDynamicCast(OSNumber, dictionary->getObject("FadePeriod"));
        const int32_t requested = (int32_t)brightness->unsigned32BitValue();
        const uint32_t goal = requested < 0 ? 0 : (uint32_t)requested > kMaxLevel ? kMaxLevel : (uint32_t)requested;
        uint64_t milliseconds = fadePeriod ? ((uint64_t)fadePeriod->unsigned32BitValue() * 1000) >> 16 : 0;
        if (milliseconds > 5000) milliseconds = 5000;
        bump(1);
        // Handed to the work loop without waiting for it (a runAction here blocks backboardd on the work loop's gate, sheng int-277); a
        // newer request replaces one not yet taken. The request timer carries it (the interrupt source did not, sheng int-278).
        __atomic_store_n(&gRequest, 1ull << 63 | (uint64_t)goal << 16 | milliseconds, __ATOMIC_RELEASE);
        post();
        publish(goal);
        return kIOReturnSuccess;
    }
};
// arm64 (no ptrauth): the plain definition; impersonate() swaps getMetaClass through a copied vtable.
OSDefineMetaClassAndStructors(RuanBacklightSvc, IOService)

static RuanBacklightSvc *gService;

// Called by RuanBacklight.cpp once this file's classes are registered (its static initializer runs between preModLoad and postModLoad),
// with the SE mapped after its clock and protocol checks. The service starts with the chip reads in flight and publishes when answered.
extern "C" bool ruan_bl_svc_start(volatile uint32_t *se) {
    RuanBacklightSvc *backlight = OSTypeAlloc(RuanBacklightSvc);
    if (!backlight || !backlight->init() || !backlight->attach(IOService::getPlatform()) || !backlight->startBacklight(se)) {
        if (backlight) backlight->release();
        ruan_bl_svc_stats[0] = -3;
        return false;
    }
    gService = backlight;   // the registry keeps it; never freed
    backlight->release();
    return true;
}

// USB debug "backlight N": the same path as a slider move, without a fade. Never waits.
extern "C" int ruan_bl_svc_set_level(uint32_t level) {
    if (!gService || !g_ruan_backlight.ready) return -1;
    __atomic_store_n(&gRequest, 1ull << 63 | (uint64_t)(level > kMaxLevel ? kMaxLevel : level) << 16, __ATOMIC_RELEASE);
    gService->post();
    return 0;
}

// USB debug "backlight reg": queued to the work loop; the USB thread (not the UI) waits up to 200 ms for the answer.
extern "C" int ruan_bl_svc_reg(uint8_t reg, int value) {
    if (!gService || !g_ruan_backlight.ready) return -1;
    uint32_t idle = 0;
    if (!__atomic_compare_exchange_n(&gDebug, &idle, 1u << 31 | (value >= 0 ? 1u << 16 | (uint32_t)(value & 0xff) << 8 : 0) | reg, false,
                                     __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return -1;
    gService->post();
    for (int ms = 0; ms < 200 && __atomic_load_n(&gDebug, __ATOMIC_ACQUIRE); ms++) IOSleep(1);
    // shortcut: a timed-out request stays queued and is answered later into gDebugResult, nobody reads it; fine for a debug command.
    return __atomic_load_n(&gDebug, __ATOMIC_ACQUIRE) ? -1 : __atomic_load_n(&gDebugResult, __ATOMIC_ACQUIRE);
}

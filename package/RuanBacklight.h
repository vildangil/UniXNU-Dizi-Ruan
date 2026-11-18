// SPDX-License-Identifier: BSD-2-Clause-Patent
// RuanBacklight: Apple XNU display backlight driver for Xiaomi Redmi Pad Pro 5G ("ruan", SM7435).
#ifndef _RUAN_BACKLIGHT_H_
#define _RUAN_BACKLIGHT_H_

#include <IOKit/IOService.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>

#ifdef __cplusplus
extern "C" {
#endif

// Live brightness state
struct ruan_backlight_state {
    uint32_t current_level;   // 0..4095 (12-bit), read back from the SY7758 at start
    uint32_t max_level;       // 4095
    uint32_t min_level;       // floor for writes, so the screen never goes fully dark
    bool     ready;           // clocks on, I2C engine found, chip answered
    uint8_t  dev_id;          // SY7758 REG 0x03
    uint32_t last_irq;        // GENI M_IRQ status of the last failed transfer (all ones = timeout)
    uint64_t updates_count;
    uint32_t errors;
    char     status[96];
};

extern struct ruan_backlight_state g_ruan_backlight;

// C entry points
void ruan_backlight_init(void);
int  ruan_backlight_set_level(uint32_t level); // 0..4095
uint32_t ruan_backlight_get_level(void);
int  ruan_backlight_reg(uint8_t reg, int value);   // value < 0: read only
bool ruan_backlight_start(void);

#ifdef __cplusplus
}

class RuanBacklight : public IOService {
public:
    virtual bool init(OSDictionary *propTable = nullptr) override;
    virtual bool start(IOService *provider) override;
    virtual void stop(IOService *provider) override;
    virtual IOReturn setProperties(OSObject *properties) override;

    void setLevel(uint32_t value);
    void publish(uint32_t value);
    void beginFade(uint32_t goal, uint32_t milliseconds);

    static void fadeStep(OSObject *owner, IOTimerEventSource *sender);
    static void requestFired(OSObject *owner, IOTimerEventSource *sender);

private:
    IOWorkLoop *m_loop = nullptr;
    IOTimerEventSource *m_fade = nullptr;
    IOTimerEventSource *m_request = nullptr;

    uint32_t m_level = 0;
    uint32_t m_from = 0;
    uint32_t m_to = 0;
    uint64_t m_start = 0;
    uint64_t m_period = 0;
};

#endif /* __cplusplus */

#endif /* _RUAN_BACKLIGHT_H_ */

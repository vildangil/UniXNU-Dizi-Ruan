// SPDX-License-Identifier: BSD-2-Clause-Patent
/*
 * RuanBattery.h - Native Battery and PowerSource Subsystem for Redmi Pad Pro 5G ("ruan")
 * Interfaces Qualcomm PM7250B / PMK8350 SPMI ADC channels with Apple IOPMPowerSource.
 */
#ifndef RUAN_BATTERY_H
#define RUAN_BATTERY_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

struct hakios_battery_state {
	uint32_t size;
	int32_t percent_hundredths;     /* e.g. 7850 = 78.50% */
	int32_t voltage_uv;             /* microvolts, e.g. 3920000 = 3.92V */
	int32_t current_ua;             /* microamps (>0 charging, <0 discharging) */
	int32_t temperature_hundredths; /* hundredths of deg C, e.g. 2800 = 28.0C */
	int32_t present;                /* 1 if battery installed */
	int32_t external;               /* 1 if charger/USB connected */
	int32_t status;                 /* 1: charging, 2: discharging, 4: full */
	int32_t charge_uah;             /* current charge in uAh */
	int32_t full_uah;               /* capacity at full charge in uAh */
	int32_t design_uah;             /* design capacity (10000 mAh = 10000000 uAh) */
	int32_t cycles;                 /* cycle count */
	int32_t usb_type;               /* 1: SDP, 2: DCP, 5: Type-C, 6: PD */
	int32_t usb_voltage_uv;         /* USB VBUS voltage */
	int32_t usb_current_ua;         /* USB input current */
};

extern struct hakios_battery_state g_ruan_battery;

void ruan_battery_init(void);
void ruan_battery_poll(void);
void HakiosBatteryReport(const void *state, unsigned size);

#ifdef __cplusplus
}
#endif

#endif /* RUAN_BATTERY_H */

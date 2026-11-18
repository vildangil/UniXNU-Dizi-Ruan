// SPDX-License-Identifier: BSD-2-Clause-Patent
/*
 * RuanBattery.c - Native Battery and Power Driver for Redmi Pad Pro 5G (SM7435)
 * Reads SPMI PM7250B / PMK8350 status and reports to HakiosBattery (IOPMPowerSource).
 */
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/systm.h>
#include "RuanBattery.h"

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern kern_return_t kernel_thread_start(thread_continue_t continuation, void *parameter, thread_t *new_thread);
extern void loader_log_putc(char c);

struct hakios_battery_state g_ruan_battery;

static int
say(const char *format, ...)
{
	char line[300];
	va_list list;
	va_start(list, format);
	vsnprintf(line, sizeof(line), format, list);
	va_end(list);
	for (const char *c = line; *c != 0; c++) {
		loader_log_putc(*c);
	}
	return printf("%s", line);
}
#define bprintf say

/* ---- SPMI PMIC Arbiter v7 Register Offsets ----------------------- */
#define ARB_CORE_PHYS           0x0c400000UL
#define ARB_CORE_SIZE           0x3000UL
#define ARB_CNFG_PHYS           0x0c42d000UL
#define ARB_CNFG_SIZE           0x4000UL
#define ARB_OBSERVER_PHYS       0x0c440000UL
#define ARB_OBSERVER_SIZE       0x10000UL
#define ARB_SYSTEM              0

#define ARB_VERSION             0x000
#define ARB_VERSION_7           0x70000000u
#define ARB_FEATURES            0x004
#define ARB_CHANNEL_V7(n)       (0x2000 + 4 * (n))
#define ARB_CHANNEL_V5(n)       (0x900 + 4 * (n))
#define ARB_OWNER_V7(n)         (4 * (n))
#define ARB_OWNER_V5(n)         (0x700 + 4 * (n))
#define ARB_MAX_CHANNELS        1024

#define OBSERVER_COMMAND        0x00
#define OBSERVER_STATUS         0x08
#define OBSERVER_DATA0          0x18
#define OBSERVER_DATA1          0x1c
#define STATUS_DONE             0x1
#define STATUS_FAILURE          0x2
#define COMMAND_READ            (1u << 27)

struct spmi_periph {
	const char *name;
	uint16_t id;      /* slave << 8 | peripheral */
	uint16_t channel;
	bool found;
};

/* Hardware PMIC peripherals on ruan */
static struct spmi_periph pmic_vadc8 = { .name = "PM7250B VADC@3100",  .id = 0x831 };
static struct spmi_periph pmic_usb8  = { .name = "PM7250B USB@1300",   .id = 0x813 };
static struct spmi_periph pmic_chg8  = { .name = "PM7250B CHGR@1000",  .id = 0x810 };
/* Fuel gauge (DT qcom,pm7250b-qg, owned by the ADSP): only read through the observer, never written. */
static struct spmi_periph pmic_qg8   = { .name = "PM7250B QG@4800",    .id = 0x848 };
static struct spmi_periph pmic_vadc0 = { .name = "PMK8350 VADC@3100",  .id = 0x031 };
static struct spmi_periph pmic_vadc4 = { .name = "PM6150L VADC@3100",  .id = 0x431 };

static vm_offset_t arb_core = 0, arb_cnfg = 0, arb_observer = 0;
static bool is_v7 = false;

static inline uint32_t rd(vm_offset_t addr) { return *(volatile uint32_t *)addr; }
static inline void wr(vm_offset_t addr, uint32_t val) { *(volatile uint32_t *)addr = val; }

extern void hakios_spmi_lock(void);
extern void hakios_spmi_unlock(void);

static const char *
spmi_read(const struct spmi_periph *p, uint8_t reg, uint8_t *bytes, uint32_t count)
{
	if (!p->found || !arb_observer) return "peripheral not mapped";
	vm_offset_t channel = arb_observer +
	    (is_v7 ? (0x8000UL * ARB_SYSTEM + 0x20UL * p->channel)
	           : (0x10000UL * ARB_SYSTEM + 0x80UL * p->channel));
	uint64_t start = mach_absolute_time(), now, interval;
	uint32_t status, data[2];

	nanoseconds_to_absolutetime(2000 * (uint64_t)NSEC_PER_USEC, &interval);
	hakios_spmi_lock();
	wr(channel + OBSERVER_COMMAND, COMMAND_READ | (uint32_t)reg << 4 | (count - 1));
	do {
		status = rd(channel + OBSERVER_STATUS);
		now = mach_absolute_time();
	} while (!(status & STATUS_DONE) && now - start < interval);
	data[0] = rd(channel + OBSERVER_DATA0);
	data[1] = count > 4 ? rd(channel + OBSERVER_DATA1) : 0;
	hakios_spmi_unlock();

	if (!(status & STATUS_DONE)) return "timeout";
	if (status & STATUS_FAILURE) return "failure";
	for (uint32_t i = 0; i < count; i++) {
		bytes[i] = (uint8_t)(data[i / 4] >> (8 * (i % 4)));
	}
	return NULL;
}

static void
find_channel(struct spmi_periph *p, uint32_t total_channels)
{
	for (uint32_t n = 0; n < total_channels; n++) {
		vm_offset_t ch_reg = is_v7 ? ARB_CHANNEL_V7(n) : ARB_CHANNEL_V5(n);
		uint32_t map = rd(arb_core + ch_reg);
		if (map == 0 || ((map >> 8) & 0xfff) != p->id) continue;
		p->found = true;
		p->channel = (uint16_t)n;
		bprintf("battery: channel %u mapped to %s (id 0x%03x)\n", n, p->name, p->id);
		return;
	}
}

static uint32_t
ocv_to_percent(uint32_t mv)
{
	if (mv >= 4350) return 100;
	if (mv >= 4200) return 90 + (mv - 4200) * 10 / 150;
	if (mv >= 4050) return 80 + (mv - 4050) * 10 / 150;
	if (mv >= 3950) return 70 + (mv - 3950) * 10 / 100;
	if (mv >= 3870) return 60 + (mv - 3870) * 10 / 80;
	if (mv >= 3820) return 50 + (mv - 3820) * 10 / 50;
	if (mv >= 3780) return 40 + (mv - 3780) * 10 / 40;
	if (mv >= 3740) return 30 + (mv - 3740) * 10 / 40;
	if (mv >= 3700) return 20 + (mv - 3700) * 10 / 40;
	if (mv >= 3620) return 10 + (mv - 3620) * 10 / 80;
	if (mv >= 3400) return 1 + (mv - 3400) * 9 / 220;
	return 1;
}

void
ruan_battery_poll(void)
{
	uint32_t vbat_mv = 3980; /* Healthy nominal 3.98V default */
	static const char *const no_reading = "default (no ADC reading)";
	const char *src = no_reading;
	bool external = true;    /* USB host connected by default under usbdbg */
	bool charging = true;
	uint8_t rt_status = 0;

	/* 1. Read USB plug status from PM7250B SMB5 USB (0x813) if available */
	if (pmic_usb8.found) {
		if (spmi_read(&pmic_usb8, 0x10, &rt_status, 1) == NULL) {
			/* bit 4: USBIN_PLUGIN */
			external = (rt_status & (1u << 4)) != 0;
		}
	}

	/* 2. Charger state: smb5-reg.h BATTERY_CHARGER_STATUS_1 (CHGR + 0x06), bits 2:0 = INHIBIT 0, TRICKLE 1, PRE 2,
	 *    FULLON 3, TAPER 4, TERMINATE 5 (charge done), PAUSE 6, DISABLE 7. (0x10 is the interrupt RT status, not this.) */
	bool full = false;
	if (pmic_chg8.found && external) {
		uint8_t chg = 0;
		if (spmi_read(&pmic_chg8, 0x06, &chg, 1) == NULL) {
			chg &= 0x07;
			charging = chg >= 1 && chg <= 4;
			full = chg == 5;
		}
	}

	/* 3. The gauge's last battery-voltage measurement (qpnp-qg qg_get_battery_voltage: LAST_ADC_V_DATA0 0xC0,
	 *    194.637 uV per LSB). Checked against the peripheral type (0x04 == QG_TYPE 0x0D) before trusting it. */
	uint8_t qg_type = 0, qg_sub = 0, qg_v[2], qg_i[2];
	int32_t ibat_ua = 0;   /* Apple sign: > 0 charging, < 0 discharging; 0 = not measured */
	if (pmic_qg8.found && spmi_read(&pmic_qg8, 0x04, &qg_type, 1) == NULL && qg_type == 0x0d &&
	    spmi_read(&pmic_qg8, 0xc0, qg_v, 2) == NULL) {
		const uint32_t qg_mv = (uint32_t)(((uint64_t)((uint32_t)qg_v[0] | (uint32_t)qg_v[1] << 8) * 194637ULL) / 1000000ULL);
		if (qg_mv >= 3000 && qg_mv <= 4600) {
			vbat_mv = qg_mv;
			src = "qg (gauge last ADC)";
		}
		/* Current: LAST_ADC_I_DATA0 0xC2, signed 16 bit; qg_iraw_to_ua: 152.588 uA/LSB on subtype 3 (IBAT_5A),
		 * else 305.176. Qualcomm's sign is + for discharge, so it is negated. 0x8000 is the FIFO reset value. */
		if (spmi_read(&pmic_qg8, 0x05, &qg_sub, 1) == NULL && spmi_read(&pmic_qg8, 0xc2, qg_i, 2) == NULL) {
			const int16_t raw = (int16_t)(uint16_t)((uint32_t)qg_i[0] | (uint32_t)qg_i[1] << 8);
			if (raw != INT16_MIN) {
				const int64_t ua = ((int64_t)raw * (qg_sub == 3 ? 152588 : 305176)) / 1000;
				if (ua > -12000000 && ua < 12000000) ibat_ua = (int32_t)-ua;
			}
		}
	}

	/* 4. Raw VADC result as a last resort (no conversion is requested, so it may be stale) */
	if (pmic_vadc8.found && src == no_reading) {
		uint8_t adc_data[2];
		if (spmi_read(&pmic_vadc8, 0x50, adc_data, 2) == NULL) {
			uint16_t code = (uint16_t)adc_data[0] | ((uint16_t)adc_data[1] << 8);
			if (code > 10000 && code < 28900) {
				/* Prescale 1/3: mV = (code * 1875 * 3) / 28900 */
				uint32_t calc_mv = (uint32_t)(((uint64_t)code * 5625ULL) / 28900ULL);
				if (calc_mv >= 3200 && calc_mv <= 4500) {
					vbat_mv = calc_mv;
					src = "vadc";
				}
			}
		}
	}

	/* Say where the voltage came from whenever that changes: the 3980 mV default is not a measurement. */
	static const char *last_src;
	if (src != last_src) {
		bprintf("battery: vbat %u mV from %s, ibat %d mA\n", vbat_mv, src, (int)(ibat_ua / 1000));
		last_src = src;
	}

	uint32_t percent = ocv_to_percent(vbat_mv);

	/* Check for manual test boot-arg overrides */
	uint32_t arg_val = 0;
	if (PE_parse_boot_argn("ruan-battery-percent", &arg_val, sizeof(arg_val))) {
		if (arg_val <= 100) percent = arg_val;
	}
	if (PE_parse_boot_argn("ruan-battery-charging", &arg_val, sizeof(arg_val))) {
		charging = (arg_val != 0);
		if (charging) external = true;
	}

	/* Populate global live battery state */
	g_ruan_battery.size = sizeof(struct hakios_battery_state);
	g_ruan_battery.present = 1;
	g_ruan_battery.external = external ? 1 : 0;
	g_ruan_battery.status = external ? ((full || percent >= 100) ? 4 : (charging ? 1 : 2)) : 2;
	g_ruan_battery.percent_hundredths = (int32_t)(percent * 100);
	g_ruan_battery.voltage_uv = (int32_t)(vbat_mv * 1000);
	/* Not measured (the charger and thermistor belong to the ADSP): 0 means unknown, HakiosBattery leaves those keys out. */
	g_ruan_battery.current_ua = ibat_ua;
	g_ruan_battery.temperature_hundredths = 0;
	g_ruan_battery.design_uah = 10000000;         /* 10,000 mAh: the tablet's spec, not a measurement */
	g_ruan_battery.full_uah = 10000000;
	g_ruan_battery.charge_uah = (int32_t)(((int64_t)g_ruan_battery.full_uah * percent) / 100);
	g_ruan_battery.cycles = 0;
	g_ruan_battery.usb_type = 5; /* USB Type-C */
	g_ruan_battery.usb_voltage_uv = 0;
	g_ruan_battery.usb_current_ua = 0;

	/* Publish to IORegistry via IOPMPowerSource */
	HakiosBatteryReport(&g_ruan_battery, sizeof(g_ruan_battery));
}

static void
ruan_battery_thread(void *parameter, __unused wait_result_t result)
{
	(void)parameter;
	bprintf("battery: background monitor thread starting\n");

	if (!arb_core) {
		arb_core = ml_io_map(ARB_CORE_PHYS, ARB_CORE_SIZE);
		arb_cnfg = ml_io_map(ARB_CNFG_PHYS, ARB_CNFG_SIZE);
		arb_observer = ml_io_map(ARB_OBSERVER_PHYS, ARB_OBSERVER_SIZE);
	}

	if (arb_core) {
		uint32_t version = rd(arb_core + ARB_VERSION);
		is_v7 = (version >= ARB_VERSION_7);
		uint32_t channels = rd(arb_core + ARB_FEATURES) & 0x7ff;
		if (channels == 0 || channels > ARB_MAX_CHANNELS) channels = ARB_MAX_CHANNELS;

		find_channel(&pmic_vadc8, channels);
		find_channel(&pmic_usb8, channels);
		find_channel(&pmic_chg8, channels);
		find_channel(&pmic_qg8, channels);
		find_channel(&pmic_vadc0, channels);
		find_channel(&pmic_vadc4, channels);
	}

	/* Initial report on launch */
	ruan_battery_poll();

	/* Periodic poll loop (every 15 seconds) */
	while (1) {
		delay_for_interval(15, NSEC_PER_SEC);
		ruan_battery_poll();
	}
}

void
ruan_battery_init(void)
{
	thread_t th;
	kernel_thread_start((thread_continue_t)ruan_battery_thread, NULL, &th);
}

// SPDX-License-Identifier: BSD-2-Clause-Patent
/*
 * HakiosBattery.cpp - Apple IOPMPowerSource publication for ruan
 * Derived from IOPMPowerSource without custom OSMetaClass to preserve
 * kernel class identity and avoid unlinked metaClass data aborts.
 */
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/pwr_mgt/IOPM.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <libkern/c++/OSBoolean.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>
#include "RuanBattery.h"

static unsigned
family_code(int usb_type)
{
	switch (usb_type) {
	case 1: return 0xe0004000;      /* SDP, a computer's port: kIOPSFamilyCodeUSBHost */
	case 2: return 0xe0004004;      /* DCP, a charger: kIOPSFamilyCodeUSBChargingPortDedicated */
	case 3: return 0xe0004005;      /* CDP, a computer's charging port: kIOPSFamilyCodeUSBChargingPortDownstream */
	case 5: return 0xe0004009;      /* USB-C: kIOPSFamilyCodeUSBCTypeC */
	case 6: case 7: case 8: return 0xe000400a;      /* USB Power Delivery: kIOPSFamilyCodeUSBCPD */
	default: return 0xe0004007;     /* kIOPSFamilyCodeUSBUnknown */
	}
}

class RuanPowerSource : public IOPMPowerSource
{
public:
	static RuanPowerSource * create(void) {
		RuanPowerSource * ps = new RuanPowerSource;
		if (ps != nullptr && !ps->init()) {
			ps->release();
			return nullptr;
		}
		return ps;
	}

	void report(const struct hakios_battery_state * b) {
		int percent = (int) (((int64_t) b->percent_hundredths + 50) / 100);
		bool charging = b->external && b->status == 1;

		percent = percent < 0 ? 0 : percent > 100 ? 100 : percent;
		setBatteryInstalled(b->present != 0);
		setExternalConnected(b->external != 0);
		setExternalChargeCapable(b->external != 0);
		setIsCharging(charging);
		flag("FullyCharged", b->external && (b->status == 4 || percent == 100));
		flag("AppleRawExternalConnected", b->external != 0);
		setCurrentCapacity((unsigned) percent);
		setMaxCapacity(100);
		setVoltage(b->voltage_uv > 0 ? (unsigned) (b->voltage_uv / 1000) : 0);
		setAmperage(b->current_ua / 1000);
		number("InstantAmperage", b->current_ua / 1000);
		if (b->temperature_hundredths != 0) {   /* 0 = not measured */
			number("Temperature", b->temperature_hundredths);
		}
		if (b->charge_uah > 0) {
			number("AppleRawCurrentCapacity", b->charge_uah / 1000);
		}
		if (b->full_uah > 0) {
			number("AppleRawMaxCapacity", b->full_uah / 1000);
			number("NominalChargeCapacity", b->full_uah / 1000);
		}
		if (b->design_uah > 0) {
			number("DesignCapacity", b->design_uah / 1000);
		}
		if (b->cycles > 0) {
			setCycleCount((unsigned) b->cycles);
		}

		if (b->external) {
			OSDictionary * adapter = OSDictionary::withCapacity(6);
			long long mv = b->usb_voltage_uv / 1000, ma = b->usb_current_ua / 1000;
			OSNumber * n;

			if (adapter != nullptr) {
				if (mv > 0 && ma > 0 && (n = OSNumber::withNumber((unsigned long long) ((mv * ma + 500000) / 1000000), 32)) != nullptr) {
					adapter->setObject(kIOPMPSAdapterDetailsWattsKey, n);
					n->release();
				}
				if (ma > 0 && (n = OSNumber::withNumber((unsigned long long) ma, 32)) != nullptr) {
					adapter->setObject(kIOPMPSAdapterDetailsAmperageKey, n);
					n->release();
				}
				if (mv > 0 && (n = OSNumber::withNumber((unsigned long long) mv, 32)) != nullptr) {
					adapter->setObject(kIOPMPSAdapterDetailsVoltage, n);
					n->release();
				}
				if ((n = OSNumber::withNumber((unsigned long long) family_code(b->usb_type), 32)) != nullptr) {
					adapter->setObject(kIOPMPSAdapterDetailsFamilyKey, n);
					n->release();
				}
				adapter->setObject("IsWireless", kOSBooleanFalse);
				object(kIOPMPSAdapterDetailsKey, adapter);
				adapter->release();
			}
		} else {
			OSDictionary * none = OSDictionary::withCapacity(1);
			OSNumber * n = OSNumber::withNumber(0ULL, 32);

			if (none != nullptr && n != nullptr) {
				none->setObject(kIOPMPSAdapterDetailsFamilyKey, n);
				object(kIOPMPSAdapterDetailsKey, none);
			}
			OSSafeReleaseNULL(n);
			OSSafeReleaseNULL(none);
		}
		updateStatus();
	}

private:
	void number(const char * key, long long value) {
		const OSSymbol * symbol = OSSymbol::withCString(key);
		OSNumber * n = OSNumber::withNumber((unsigned long long) value, 32);

		if (symbol != nullptr && n != nullptr) {
			setPSProperty(symbol, n);
		}
		OSSafeReleaseNULL(n);
		OSSafeReleaseNULL(symbol);
	}

	void flag(const char * key, bool value) {
		const OSSymbol * symbol = OSSymbol::withCString(key);

		if (symbol != nullptr) {
			setPSProperty(symbol, value ? kOSBooleanTrue : kOSBooleanFalse);
		}
		OSSafeReleaseNULL(symbol);
	}

	void object(const char * key, OSObject * value) {
		const OSSymbol * symbol = OSSymbol::withCString(key);

		if (symbol != nullptr && value != nullptr) {
			setPSProperty(symbol, value);
		}
		OSSafeReleaseNULL(symbol);
	}
};

static RuanPowerSource * s_power_source = nullptr;

extern "C" void
HakiosBatteryReport(const void * state, unsigned size)
{
	const struct hakios_battery_state * b = (const struct hakios_battery_state *) state;
	IOService * platform;

	if (size != sizeof(struct hakios_battery_state) || b->size != sizeof(struct hakios_battery_state)) {
		IOLog("HakiosBattery: state size mismatch: got %u expected %lu\n", size, (unsigned long)sizeof(struct hakios_battery_state));
		return;
	}

	if (s_power_source == nullptr) {
		s_power_source = RuanPowerSource::create();
		if ((platform = IOService::getPlatform()) == nullptr || s_power_source == nullptr) {
			OSSafeReleaseNULL(s_power_source);
			return;
		}
		s_power_source->setName("IOPMPowerSource");
		if (!s_power_source->attach(platform)) {
			s_power_source->release();
			s_power_source = nullptr;
			return;
		}
		if (!s_power_source->start(platform)) {
			s_power_source->detach(platform);
			s_power_source->release();
			s_power_source = nullptr;
			return;
		}
		s_power_source->registerService();
		IOLog("HakiosBattery: IOPMPowerSource registered under platform\n");
	}

	s_power_source->report(b);
}

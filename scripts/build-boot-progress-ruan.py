#!/usr/bin/env python3
"""dizi: the ruan port's board code (F-e-n-y-x/UniXNU-iPadOS-on-Redmi-Pad-Pro-5G, BSD-2-Clause-Patent; written for xnu-10063)
compiled with the flags of XNU's own compile records into build/boot-progress-ruan/libBootProgressRuan.a, linked through
CONFIG_XNU_EXTRA_LD_ARCHIVES. Run as a [kernel] archives step (cwd = the UniXNU tree).

The object list is ruan's scripts/build-ram-root-probe.py without the parts dizi does not use: its RAM root (RamRootProbe,
RamRestoreTrust, RamBlockNoStore; dizi boots from UFS and has its own Data volume), the Adreno 710 bring-up (RuanGpuPower,
AdrenoHfi: experimental, and it needs Qualcomm's GPU firmware), the Wi-Fi and audio status stubs, and the key store (dizi builds
it in scripts/build-keystore-probe.py). package/BootProgressRuanStubs.c stands in for what is left out.

The touch firmware headers are generated from stock vendor firmware and stay out of git: .cache/hakios-fw in the device
repository holds hakios.novatek_ruan_fw.h (/vendor/firmware/novatek_ts_fw_boe.bin) and a placeholder
hakios.focaltech_garnet_fw.h (the garnet phone's touch path, unused on dizi).
"""
import json, os, struct, subprocess
from pathlib import Path

ROOT = Path('.').resolve()
DEVICE = Path(os.environ.get('UNIXNU_DEVICE', ROOT.parent))
OUT = ROOT / 'build/boot-progress-ruan'
OUT.mkdir(parents=True, exist_ok=True)
FW = DEVICE / '.cache/hakios-fw'


def flags(record_name):
    return json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837' / record_name).read_text().strip().rstrip(','))


def build(command, record, obj):
    result = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True)
    (OUT / (obj.stem + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    return obj


def compile_like(record_name, source, obj, extra=()):
    """ruan's compile_like: a C board file with the flags of an XNU C compile record."""
    record = flags(record_name)
    command, arguments, i = [], record['arguments'], 0
    while i < len(arguments):
        value = arguments[i]
        if value == record['file']:
            command.append(str(source))
        elif value in ('-o', '-MF', '-MT', '-MJ'):
            if value == '-o':
                command += ['-o', str(obj)]
            i += 1
        elif value == '-Xclang' and arguments[i + 1].startswith('-W'):
            i += 1
        elif not value.startswith('-W') and value not in ('-MD', '-MP'):
            command.append(value)
        i += 1
    command += ['-I', str(OUT), '-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror', *extra]
    build(command, record, obj)
    if struct.unpack_from('<4I', obj.read_bytes()) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit(f'{obj}: expected an ordinary ARM64 Mach-O object')
    return obj


def compile_cxx_like(record_name, source, obj, extra=()):
    """ruan's compile_cxx_like: a C++ board file with an IOKit compile record; the record's -Wno- switches stay."""
    record = flags(record_name)
    command, suppressions, arguments, i = [], [], record['arguments'], 0
    while i < len(arguments):
        value = arguments[i]
        if value == record['file']:
            command.append(str(source))
        elif value in ('-o', '-MF', '-MT', '-MJ'):
            if value == '-o':
                command += ['-o', str(obj)]
            i += 1
        elif value == '-Xclang' and arguments[i + 1].startswith('-W'):
            i += 1
        elif value.startswith('-Wno-'):
            suppressions.append(value)
        elif not value.startswith('-W') and value not in ('-MD', '-MP'):
            command.append(value)
        i += 1
    command += ['-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                '-Wno-unnecessary-virtual-specifier', '-Wno-c99-designator', '-Wno-reorder-init-list',
                '-Wno-deprecated-enum-enum-conversion', '-I', str(record['directory']),
                '-I', str(ROOT / '.cache/xnu-work/osfmk'), '-I', str(OUT), *extra, *suppressions]
    return build(command, record, obj)


def late_object(obj, source_name):
    """ruan's recipe: drop the object's __mod_init_func and globalize its static initializer, so the class registers only when the
    board code calls __GLOBAL__sub_I_<source> (as the key store's NativeKeyStoreEvents)."""
    late = obj.with_suffix('.late.o')
    subprocess.run(['llvm-objcopy', '--remove-section=__DATA,__mod_init_func', f'--globalize-symbol=__GLOBAL__sub_I_{source_name}',
                    obj, late], check=True)
    return late


for header in ('hakios.novatek_ruan_fw.h', 'hakios.focaltech_garnet_fw.h'):
    if not (FW / header).is_file():
        raise SystemExit(f'{FW / header} missing: generate it from the stock touch firmware (see this script\'s docstring)')

# HakiOS's C is warning-clean under its own flags, not under -Wextra -Werror (ruan).
HAKIOS_C = ['-I', str(FW), '-Wno-error', '-Wno-unused-function', '-Wno-unused-parameter', '-Wno-unused-variable',
            '-Wno-unused-but-set-variable', '-Wno-sign-compare', '-Wno-missing-prototypes']
PKG = DEVICE / 'package'
STARTUP, EXEC, PE = 'osfmk/DEVELOPMENT/startup.o.json', 'bsd/DEVELOPMENT/kern_exec.o.json', 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
objects = [
    # the boot-progress page (ruan's package/BootProgress.c) and the stand-ins for what dizi leaves out
    compile_like(STARTUP, PKG / 'BootProgressRuan.c', OUT / 'BootProgressRuan.o'),
    compile_like(STARTUP, PKG / 'BootProgressRuanStubs.c', OUT / 'BootProgressRuanStubs.o'),
    # reboot into fastboot (ruan-autoreset, USB reboot-fastboot) and the crash banner's fault records
    compile_like(STARTUP, PKG / 'BootReset.c', OUT / 'BootReset.o'),
    compile_like(STARTUP, PKG / 'BootFaultProbe.c', OUT / 'BootFaultProbe.o'),
    # touch (NT36532, ruan_touch=1) and buttons (garnet_buttons=1), HakiOS drivers feeding NativeHidInput
    compile_like(EXEC, PKG / 'RuanInput.c', OUT / 'RuanInput.o'),
    compile_like(EXEC, PKG / 'RuanTouch.c', OUT / 'RuanTouch.o', HAKIOS_C),
    compile_like(EXEC, PKG / 'RuanButtons.c', OUT / 'RuanButtons.o', HAKIOS_C),
    # battery (PM7250B fuel gauge) as an IOPMPowerSource, and the SY7758 backlight over GENI I2C
    compile_like(EXEC, PKG / 'RuanBattery.c', OUT / 'RuanBattery.o', HAKIOS_C),
    compile_cxx_like(PE, PKG / 'HakiosBattery.cpp', OUT / 'HakiosBattery.o'),
    compile_cxx_like(PE, PKG / 'RuanBacklight.cpp', OUT / 'RuanBacklight.o'),
    # the conforming backlight service (AppleARMBacklight): libEDR inside backboardd starts only for it; without it every frame
    # waited 5 s in mach_msg (ruan 2026-11-21). Its static initializer runs when RuanBacklight.cpp starts it (ruan-bl-svc).
    compile_like(EXEC, PKG / 'GeniI2c.c', OUT / 'GeniI2c.o', HAKIOS_C),   # the service's non-blocking GENI I2C transfers
    late_object(compile_cxx_like(PE, PKG / 'RuanBacklightSvc.cpp', OUT / 'RuanBacklightSvc.o'), 'RuanBacklightSvc.cpp'),
    # CPU frequency (EPSS vote, ruan-cpufreq=2)
    compile_like(STARTUP, PKG / 'RuanCpuFreq.c', OUT / 'RuanCpuFreq.o'),
]
archive = OUT / 'libBootProgressRuan.a'
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', archive, *objects], check=True)
# The kernel build does not track this archive (XNU_EXTRA_LD_ARCHIVES): drop the linked kernel when it changes (ruan).
(ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped').unlink(missing_ok=True)
print(archive)

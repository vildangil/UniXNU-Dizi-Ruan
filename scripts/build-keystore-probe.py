#!/usr/bin/env python3
"""dizi: the AppleKeyStore stand-in, as build/keystore-probe/libKeyStoreProbe.a (linked through CONFIG_XNU_EXTRA_LD_ARCHIVES).

The ruan port's recipe (scripts/build-ram-root-probe.py, from UniXNU-gts7xlwifi): UniXNU's AppleKeyStoreState object with its
module initialiser removed and globalised, so the class registers only when package/KeyStoreProbe.cpp asks (between
preModLoad and postModLoad), plus that probe. patches/xnu/dizi-keystore-probe.patch calls native_keystore_probe() before
launchd; it does nothing without aks=1 and offline-key-events=1. Run as a [kernel] archives step (cwd = the UniXNU tree).
"""
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path('.').resolve()
OUT = ROOT / 'build/keystore-probe'
OUT.mkdir(parents=True, exist_ok=True)
PROBE = next(iter(sorted(ROOT.glob('kits/*/KeyStoreProbe.cpp'))), None)
if PROBE is None:
    raise SystemExit('Expected the device package with KeyStoreProbe.cpp under kits/')

record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json')
                    .read_text().strip().rstrip(','))


def compile_cxx(source, obj):
    """The kernel's IOKit C++ recipe; the record's -Wno- switches stay, since XNU's own headers need them under -Wextra."""
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
                '-Wno-deprecated-enum-enum-conversion', '-Wno-missing-designated-field-initializers',
                '-I', str(record['directory']), '-I', str(ROOT / '.cache/xnu-work/osfmk'), '-I', str(OUT), *suppressions]
    result = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True)
    (OUT / (obj.stem + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    return obj


subprocess.run(['python3', ROOT / 'scripts/build-arm-driver.py', 'AppleKeyStoreState'], check=True)
events = ROOT / 'build/apple-key-store-state/NativeKeyStoreEvents.o'
late = OUT / 'NativeKeyStoreEvents.late.o'
subprocess.run([shutil.which('llvm-objcopy'), '--remove-section=__DATA,__mod_init_func',
                '--globalize-symbol=__GLOBAL__sub_I_NativeKeyStoreEvents.cpp', events, late], check=True)
probe = compile_cxx(PROBE, OUT / 'KeyStoreProbe.o')
archive = OUT / 'libKeyStoreProbe.a'
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', archive, late, probe], check=True)
print(archive)

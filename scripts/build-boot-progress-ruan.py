#!/usr/bin/env python3
"""Compile package/BootProgressRuan.c (the boot-progress page of the ruan port, F-e-n-y-x/UniXNU-iPadOS-on-Redmi-Pad-Pro-5G,
BSD-2-Clause-Patent; written for xnu-10063) with the flags of XNU's own startup.c into build/boot-progress-ruan/libBootProgressRuan.a,
linked through CONFIG_XNU_EXTRA_LD_ARCHIVES. Run as a [kernel] archives step (cwd = the UniXNU tree). The compile helper is ruan's
compile_like from scripts/build-ram-root-probe.py."""
import json, os, struct, subprocess
from pathlib import Path

ROOT = Path('.').resolve()
DEVICE = Path(os.environ.get('UNIXNU_DEVICE', ROOT.parent))
OUT = ROOT / 'build/boot-progress-ruan'
OUT.mkdir(parents=True, exist_ok=True)


def compile_like(record_name, source, obj):
    record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837' / record_name).read_text().strip().rstrip(','))
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
    command += ['-I', str(OUT), '-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror']
    result = subprocess.run(command, cwd=record['directory'], capture_output=True, text=True)
    (OUT / (obj.stem + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    if struct.unpack_from('<4I', obj.read_bytes()) != (0xfeedfacf, 0x100000c, 0, 1):
        raise SystemExit(f'{obj}: expected an ordinary ARM64 Mach-O object')
    return obj


objects = [compile_like('osfmk/DEVELOPMENT/startup.o.json', DEVICE / 'package/BootProgressRuan.c', OUT / 'BootProgressRuan.o'),
           # Stand-ins for the ruan drivers dizi does not have yet (package/BootProgressRuanStubs.c).
           compile_like('osfmk/DEVELOPMENT/startup.o.json', DEVICE / 'package/BootProgressRuanStubs.c', OUT / 'BootProgressRuanStubs.o')]
archive = OUT / 'libBootProgressRuan.a'
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', archive, *objects], check=True)
print(archive)

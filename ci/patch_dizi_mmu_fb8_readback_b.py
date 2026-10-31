#!/usr/bin/env python3
"""Read-only FBFAIL8 L2 descriptor snapshot (fail-closed before native TTBR switch).

This is NOT fb-bridge-b: it never writes a PTE or proceeds to the native TTBR
switch, even when the two readbacks match the expected old snapshots.
Only the exact SHA-pinned STACK-B source is accepted. Temporary fastboot boot.
NEVER fastboot flash.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
import patch_dizi_mmu_fb_bridge_b as base

EXPECTED_BOOT = "a0ca687c085a56460ac4307e304d6025f909ac250e4b4b9201173fde902a8335"
EXPECTED_MACHO = "9b36bdd123af846f403b95d8092d78bec6dd58efcaecc42e44f4aa08a8c9f1af"
EXPECTED_TRACE = "6fc9dd0a5dbef6cce41c821fad4bd807da6d5763d3b1422b9b23a7fba1be5fbf"
TRACER_BYTES = 1308
MAX_ROW = 264
FONT_BYTES = 413
HEX_CHARS = 16
sha = base.sha


def compile_tracer(source: str, font: bytes) -> bytes:
    assert len(font) == FONT_BYTES
    if source.count('FONT_DATA') != 1:
        raise ValueError('Expected one font placeholder')
    source = source.replace('FONT_DATA', '.byte ' + ','.join(map(str, font)))
    clang = shutil.which('clang-19') or shutil.which('clang-18') or shutil.which('clang')
    objcopy = shutil.which('llvm-objcopy-19') or shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    readelf = shutil.which('readelf')
    if not all((clang, objcopy, readelf)):
        raise RuntimeError('clang, llvm-objcopy and readelf are required')
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p/'trace.S').write_text(source)
        subprocess.run([clang, '--target=aarch64-none-elf', '-c', str(p/'trace.S'), '-o', str(p/'trace.o')], check=True)
        reloc = subprocess.check_output([readelf, '-r', str(p/'trace.o')], text=True)
        if 'There are no relocations in this file' not in reloc:
            raise ValueError('Unresolved relocations in diagnostic code')
        subprocess.run([objcopy, '-O', 'binary', '-j', '.text.trace', str(p/'trace.o'), str(p/'trace.bin')], check=True)
        payload = (p/'trace.bin').read_bytes()
    if len(payload) != TRACER_BYTES or len(payload) > base.CAVE_SIZE:
        raise ValueError(f'Unexpected tracer length: {len(payload)}')
    if font != bytes(FONT_BYTES) and sha(payload) != EXPECTED_TRACE:
        raise ValueError('Rebuilt tracer SHA differs from pinned build')
    if any(x not in payload for x in (b'SLOT L2 20\0', b'CODE L2 39\0', b'FB8 SLOT BUSY\0', b'FB8 CODE DIFF\0', b'FB8 BOTH DIFF\0', b'FB8 MATCH STOP\0')):
        raise ValueError('Diagnostic strings missing')
    return payload


def validate_source(source: str) -> None:
    normalized = ' '.join(line.split('//')[0].strip() for line in source.splitlines())
    for probe in ('mrs x4,TCR_EL1','mrs x4,MAIR_EL1','mrs x4,SCTLR_EL1','mrs x4,TTBR1_EL1',
                  'ldp x6,x7,[x8]','ldr x4,[x6,#0x600]','blr x16',
                  'ldr x20,[x19,#0x100]','ldr x21,[x19,#0x1c8]',
                  'cbnz x20,fb8_slot_bad','cmp x21,x5',
                  'fb8_halt:', 'wfe'):
        if probe not in normalized:
            raise ValueError(f'Missing read-only guard/readback: {probe}')
    if normalized.index('ldr x20,[x19,#0x100]') >= normalized.index('ldr x21,[x19,#0x1c8]'):
        raise ValueError('Expected both L2 readbacks in slot/code order')
    if 'str x5,[x19,#0x100]' in normalized or 'msr TTBR' in normalized or 'tlbi ' in normalized.lower() or 'smc' in normalized.lower():
        raise ValueError('This diagnostic must not modify a PTE or native TTBR')
    if normalized.count('wfe') != 1:
        raise ValueError('Single unconditional stop expected')
    if ((MAX_ROW + 28) * 6400 + 80 + HEX_CHARS * 96) > 2 * 1024 * 1024:
        raise ValueError('Screen writes exceed first 2 MiB framebuffer alias')


def build(source: Path, output: Path, report: Path) -> dict:
    if source.resolve() == output.resolve():
        raise ValueError('Output must differ from input')
    boot = source.read_bytes()
    if (len(boot) != base.BOOT_BYTES or boot[:8] != b'ANDROID!'
        or struct.unpack_from('<I', boot, 40)[0] != 4 or sha(boot) != base.INPUT_BOOT):
        raise ValueError('Expected exact hardware-tested STACK-B boot-v4')
    original = boot[base.MACHO_OFF:base.MACHO_OFF + base.MACHO_LEN]
    if sha(original) != base.INPUT_MACHO:
        raise ValueError('Unexpected STACK-B Mach-O')
    k = bytearray(original)
    start = base.off(k, base.CAVE)
    font = next((original[start+i:start+i+FONT_BYTES]
                 for i in range(base.CAVE_SIZE - FONT_BYTES + 1)
                 if sha(original[start+i:start+i+FONT_BYTES]) == base.FONT_SHA), None)
    if font is None:
        raise ValueError('Verified original font missing')
    # Restore *all* old STACK-B tracer hooks, including the pre-switch one.
    for va, opcode in base.OLD_HOOKS:
        position = base.off(k, va)
        old = struct.unpack_from('<I', k, position)[0]
        displacement = ((old & 0x3ffffff) ^ 0x2000000) - 0x2000000
        if old >> 26 != 0x5 or not base.CAVE <= va + displacement * 4 < base.CAVE + base.CAVE_SIZE:
            raise ValueError('Unexpected STACK-B hook ' + hex(va))
        struct.pack_into('<I', k, position, opcode)
    # Preserve native TTBR1/TTBR0/TLBI/DSB/ISB and original post-hook ADRP.
    if struct.unpack_from('<I', k, base.off(k, base.POST))[0] != 0xd0ffec08:
        raise ValueError('Unexpected original post-switch ADRP')
    if struct.unpack_from('<5I', k, base.off(k, 0xfffffff0073ea11c)) != base.EXPECTED_MMU:
        raise ValueError('Native MMU/barriers differ')
    source_text = Path(__file__).with_name('dizi_mmu_fb8_readback_b.S.in').read_text()
    validate_source(source_text)
    payload = compile_tracer(source_text, font)
    k[start:start + base.CAVE_SIZE] = b'\0' * base.CAVE_SIZE
    k[start:start + len(payload)] = payload
    struct.pack_into('<I', k, base.off(k, base.PRE), base.branch(base.PRE, base.CAVE))
    allowed = set(range(start, start + base.CAVE_SIZE))
    for va, _ in base.OLD_HOOKS:
        off = base.off(k, va)
        allowed.update(range(off, off+4))
    changes = [i for i, (a,b) in enumerate(zip(original,k)) if a != b]
    if not changes or any(i not in allowed for i in changes):
        raise ValueError('Changed bytes outside tracer cave + earlier hook sites')
    # Post-switch hook MUST remain original and no other site stays hooked.
    for va, op in base.OLD_HOOKS:
        if va != base.PRE and struct.unpack_from('<I', k, base.off(k,va))[0] != op:
            raise ValueError('Old VM tracer hook not fully restored')
    result = bytearray(boot)
    result[base.MACHO_OFF:base.MACHO_OFF+base.MACHO_LEN] = k
    if sha(result) != EXPECTED_BOOT or sha(k) != EXPECTED_MACHO:
        raise ValueError("Pinned FB8 output SHA mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result)
    record = {
        'variant': 'fb8-readback-b', 'source_variant': 'stack-b',
        'hardware_tested': False, 'no_page_table_writes': True,
        'no_native_ttbr_switch': True, 'no_post_switch_hook': True,
        'input_boot_sha256': base.INPUT_BOOT, 'output_boot_sha256': sha(result),
        'output_macho_sha256': sha(k), 'payload_sha256': sha(payload),
        'payload_bytes': len(payload), 'changed_macho_bytes': len(changes),
        'raw_readbacks': {'SLOT': 'new L2[0x20] @ PA 0x804192100',
                          'CODE': 'new L2[0x39] @ PA 0x8041921c8'},
        'old_EXPECTED_SLOT': '0x0000000000000000',
        'old_EXPECTED_CODE': '0x0000000804193003',
        'pre_switch_result': 'SLOT/CODE hex + FB8 SLOT BUSY / CODE DIFF / BOTH DIFF / MATCH STOP',
        'limitation': 'Hardware runtime and effective translation UNTESTED; does not proceed to native TTBR replacement',
        'safety': 'Only temporary fastboot boot; NEVER fastboot flash'
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    return record


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('input', 'output', 'report'):
        p.add_argument('--'+arg, type=Path, required=True)
    a = p.parse_args()
    build(a.input, a.output, a.report)

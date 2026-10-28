#!/usr/bin/env python3
"""Dizi XNU: six checkpoints between _set_mmu_ttb and SCTLR_EL1.

Patch a SHA-pinned *COPY* of the five-band Mach-O only. All probes execute
with the XNU MMU still disabled. They save/restore x9-x12, NZCV and SP,
replay the exact displaced word, then branch to the original next word.
No writes to the production EDK2, and no speculative post-MMU GOP stores.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

SOURCE_SHA = '94947ff724ec85b005e7b6241e625867dadf5c10b053a1b2ae5f4f75e8b4a1d3'
ENTRY = 0xFFFFFFF0073F0488
CAVE_FIRST = ENTRY + 0x200
MARK = 'DIZI_XNU_MMU_REG_STAGES_V1'
FRAMEBUFFER_PA = 0xB8000000
STRIDE = 6400
STAGES = [
    (0xFFFFFFF0073F22B4, 0x9240BC00, 408, 0xFFFF1493, 'before TTBR1_EL1 write'),
    (0xFFFFFFF0073F22BC, 0xAA1F03E0, 432, 0xFFFF4500, 'after TTBR1_EL1 write'),
    (0xFFFFFFF0073F22FC, 0xAA010000, 456, 0xFFFFD700, 'before MAIR_EL1 write'),
    (0xFFFFFFF0073F2308, 0xD508871F, 480, 0xFF00FFC0, 'after MAIR_EL1 + ISB, before first TLBI'),
    (0xFFFFFFF0073F2330, 0x91000000, 504, 0xFF80BFFF, 'after TLBI/IC, before VBAR_EL1 write'),
    (0xFFFFFFF0073F2340, 0xF2E00000, 528, 0xFFBFFF00, 'after VBAR_EL1 write, before SCTLR_EL1'),
]

def branch(frm: int, to: int) -> int:
    diff = to - frm
    if diff % 4 or not -(1 << 27) <= diff < 1 << 27:
        raise ValueError('Unreachable branch')
    return 0x14000000 | ((diff >> 2) & 0x3FFFFFF)

def file_offset(data: bytes, va: int) -> int:
    if len(data) < 4096 or struct.unpack_from('<I', data, 0)[0] != 0xFEEDFACF:
        raise ValueError('Not 64-bit Mach-O')
    n, cmd_size = struct.unpack_from('<II', data, 16)
    if not 0 < n < 256 or cmd_size > len(data) - 32:
        raise ValueError('Invalid Mach-O commands')
    p = 32
    for _ in range(n):
        cmd, size = struct.unpack_from('<II', data, p)
        if size < 8 or p + size > len(data):
            raise ValueError('Malformed Mach-O load command')
        if cmd == 0x19:
            name, start, virt_size, off, file_size = struct.unpack_from('<16sQQQQ', data, p + 8)
            if (name.rstrip(b'\0') == b'__TEXT_EXEC' and
                    start <= va < start + min(virt_size, file_size)):
                result = off + va - start
                if result + 4 > len(data):
                    raise ValueError('File offset outside Mach-O')
                return result
        p += size
    raise ValueError(f'Executable VA missing: {va:#x}')

def assemble_stub(original_word: int, y: int, color: int) -> bytearray:
    clang = shutil.which('clang-18') or shutil.which('clang')
    objcopy = shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    if not clang or not objcopy:
        raise RuntimeError('clang and llvm-objcopy required')
    physical = FRAMEBUFFER_PA + y * STRIDE
    if not FRAMEBUFFER_PA <= physical < physical + 9 * STRIDE <= FRAMEBUFFER_PA + 2560 * STRIDE:
        raise ValueError('GOP drawing region out of range')
    asm = f'''
.section .text.probe,"ax",%progbits
.global dizi_pre_sctlr_probe
dizi_pre_sctlr_probe:
  sub sp, sp, #48
  stp x9, x10, [sp, #0]
  stp x11, x12, [sp, #16]
  mrs x12, nzcv
  str x12, [sp, #32]
  movz x9, #{physical & 0xffff}
  movk x9, #{(physical >> 16) & 0xffff}, lsl #16
  movz w10, #{color & 0xffff}
  movk w10, #{(color >> 16) & 0xffff}, lsl #16
  movz w11, #7200
1:
  stp w10, w10, [x9], #8
  subs w11, w11, #1
  b.ne 1b
  dsb sy
  ldr x12, [sp, #32]
  msr nzcv, x12
  ldp x11, x12, [sp, #16]
  ldp x9, x10, [sp, #0]
  add sp, sp, #48
  .inst {original_word:#x}
  nop
'''
    with tempfile.TemporaryDirectory(prefix='dizi-ttbr-trace-') as d:
        path = Path(d)
        (path / 'a.S').write_text(asm)
        subprocess.run([clang, '--target=aarch64-none-elf', '-c', str(path / 'a.S'), '-o', str(path / 'a.o')], check=True)
        subprocess.run([objcopy, '-O', 'binary', '-j', '.text.probe', str(path / 'a.o'), str(path / 'a.bin')], check=True)
        return bytearray((path / 'a.bin').read_bytes())

def main(input_path: Path, output_path: Path, report_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueError('Refusing to overwrite original')
    blob = bytearray(input_path.read_bytes())
    sha = hashlib.sha256(blob).hexdigest()
    if sha != SOURCE_SHA:
        raise ValueError(f'Incorrect pinned five-stage input SHA: {sha}')
    if struct.unpack_from('<II', blob, file_offset(blob, 0xFFFFFFF0073F2350)) != (0xD5181000, 0xD5033FDF):
        raise ValueError('Original MSR/ISB instructions missing')
    if struct.unpack_from('<I', blob, file_offset(blob, 0xFFFFFFF0073F234C))[0] != branch(0xFFFFFFF0073F234C, ENTRY + 0xC0):
        raise ValueError('Existing orange pre-MMU hook missing')
    position = CAVE_FIRST
    results = []
    for site, expected, y, color, meaning in STAGES:
        src_offset = file_offset(blob, site)
        if struct.unpack_from('<I', blob, src_offset)[0] != expected:
            raise ValueError(f'Unexpected {site:#x} source instruction')
        compiled = assemble_stub(expected, y, color)
        if not 64 <= len(compiled) <= 128 or len(compiled) % 4:
            raise ValueError(f'Unexpected checkpoint size: {len(compiled)}')
        if struct.unpack_from('<II', compiled, len(compiled) - 8)[0] != expected:
            raise ValueError('Displaced instruction not replayed immediately before return')
        if struct.unpack_from('<I', compiled, len(compiled) - 4)[0] != 0xD503201F:
            raise ValueError('Missing branch placeholder')
        dest_off = file_offset(blob, position)
        if any(blob[dest_off:dest_off + len(compiled)]):
            raise ValueError(f'Code cave is occupied at {position:#x}')
        struct.pack_into('<I', compiled, len(compiled) - 4,
                         branch(position + len(compiled) - 4, site + 4))
        struct.pack_into('<I', blob, src_offset, branch(site, position))
        blob[dest_off:dest_off + len(compiled)] = compiled
        results.append({'name': meaning, 'hook_va': hex(site), 'original_word': hex(expected),
                        'stub_va': hex(position), 'gop_y': [y, y + 8], 'argb': hex(color)})
        position += len(compiled)
    if position > ENTRY + 0x600:
        raise ValueError('Used more than the verified reserved code cave')
    if struct.unpack_from('<II', blob, file_offset(blob, 0xFFFFFFF0073F2350)) != (0xD5181000, 0xD5033FDF):
        raise AssertionError('MMU MSR/ISB changed')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(blob)
    meta = {
        'marker': MARK,
        'source_five_band_sha256': sha,
        'patched_sha256': hashlib.sha256(blob).hexdigest(),
        'source_bytes': len(blob),
        'stages': results,
        'original_msr_isb_unchanged': True,
        'source_untouched': True,
        'mmu_enable_verified': False,
        'interpretation': 'Each band proves entry to that hook before original instruction; only a separate post-MMU instrument can prove MMU enable.'
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(meta, indent=2) + '\n')
    print(json.dumps(meta, indent=2))

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--report', type=Path, required=True)
    a = ap.parse_args()
    main(a.input, a.output, a.report)

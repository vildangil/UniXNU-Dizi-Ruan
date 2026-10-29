#!/usr/bin/env python3
"""Reproduce one Dizi XNU MMU A/B boot-v4 test from the immutable Y504 base.

Strictly SHA-pinned, fail-closed: patch only the Mach-O tracer caves. The
original EDK2, FAT32 metadata, native TTBR1/SCTLR/ISB and boot header remain
byte-identical. Diagnostic only: not evidence of a functional XNU kernel.
NEVER flash these images; temporary fastboot boot only.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
from pathlib import Path

ENTRY = 0xFFFFFFF0073F0488
STUBS = [ENTRY + 0x200 + 84 * i for i in range(6)]
HOOKS = [
    (0xFFFFFFF0073F22B4, 0x9240BC00),
    (0xFFFFFFF0073F22BC, 0xAA1F03E0),
    (0xFFFFFFF0073F22FC, 0xAA010000),
    (0xFFFFFFF0073F2308, 0xD508871F),
    (0xFFFFFFF0073F2330, 0x91000000),
    (0xFFFFFFF0073F2340, 0xF2E00000),
]
BASE_BOOT_SHA = 'b2f22f83c9b55d5a89d60f7df42488486346754911153cc502256f686681371b'
BASE_MACHO_SHA = '6758750c684e0569eea1c00be6726bb1409f6a3c0327a555de21b3b3d134f97c'
BOOT_LEN = 68800512
FAT_OFFSET = 0x19C000
FAT_LEN = 64 * 1024 * 1024
KERNEL_OFFSET = FAT_OFFSET + 0x101200
KERNEL_LEN = 51941376
NOP = 0xD503201F
SUBS, BNE = 0x7100056B, 0x54FFFFC1
SUB, CBNZ = 0x5100056B, 0x35FFFFCB
ORANGE_CAVE = ENTRY + 0xC0
ORANGE_HOOK = 0xFFFFFFF0073F234C
SCTLR = ORANGE_HOOK + 4
EXPECTED = {
    'sixth-a': ('c7d7b268d22ee6d66a08d6955d5bbb419ff620469191491f29b0ca0dfe80c568', '7658f3c6b80840f3dc27e957e4314c1f7beddc02731a200cf80f37e7e3e493c7', 'Mu-dizi-XNU-MMU-SIX-NOSP-HIGH-RISK.img'),
    'sixth-b': ('1a15ea88e41a4f05ff21424e482ebf345b75ea935f3dca98f0728fe40b8fbe5a', 'c53aa5f23454f70676d41311b730f39e0abe2fce66d4deb5a0b440f00391e50a', 'Mu-dizi-XNU-MMU-SIX-NOSP-NZCV-HIGH-RISK.img'),
    'orange-a': ('5e9ac526a3445e3a68d611c99a1a22e0a1b54ad4d0fcfe66de88969dc6b64c9b', '7987c01efb988d722a9a3fdef94c28d5031855ab303fe9f248c62f3b698c774c', 'Mu-dizi-XNU-ORANGE-NOSP-A-HIGH-RISK.img'),
    'orange-b': ('58ba8bb76ad326ea765a92299ef845e2fa574cbf94c181c5249e42da1250293e', '1c245f4da986e6ea57f928246064939ddcdc44c4833535184fa78b60532e060e', 'Mu-dizi-XNU-ORANGE-NOSP-B-NZCV-HIGH-RISK.img'),
}


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def arm_b(frm: int, to: int) -> int:
    d = to - frm
    if d % 4 or not -(1 << 27) <= d < (1 << 27):
        raise ValueError('Unreachable ARM64 B')
    return 0x14000000 | ((d >> 2) & 0x3ffffff)


def off(b: bytes, addr: int) -> int:
    if struct.unpack_from('<I', b)[0] != 0xfeedfacf:
        raise ValueError('Expected Mach-O64')
    n, length = struct.unpack_from('<II', b, 16)
    if not 0 < n < 256 or length > len(b)-32:
        raise ValueError('Invalid Mach-O load commands')
    p, end = 32, 32 + length
    for _ in range(n):
        if p+8 > end:
            raise ValueError('Truncated command')
        kind, size = struct.unpack_from('<II', b, p)
        if size < 8 or p+size > end:
            raise ValueError('Bad command bounds')
        if kind == 0x19:
            if size < 72:
                raise ValueError('Truncated LC_SEGMENT_64')
            name, vm, vs, foff, fs = struct.unpack_from('<16sQQQQ', b, p+8)
            if name.rstrip(b'\0') == b'__TEXT_EXEC' and vm <= addr < vm+min(vs, fs):
                result = foff + addr - vm
                if result < 0 or result+4 > len(b):
                    raise ValueError('Invalid executable offset')
                return result
        p += size
    raise ValueError(f'Address missing in __TEXT_EXEC: {addr:#x}')


def read_base(boot: bytes) -> bytearray:
    if len(boot) != BOOT_LEN or sha(boot) != BASE_BOOT_SHA:
        raise ValueError('Refusing non-pinned Y504 base boot.img')
    if boot[:8] != b'ANDROID!' or struct.unpack_from('<I', boot, 40)[0] != 4:
        raise ValueError('Wrong Android boot version')
    fat = memoryview(boot)[FAT_OFFSET:FAT_OFFSET+FAT_LEN]
    geometry = (struct.unpack_from('<H', fat, 11)[0], fat[13], struct.unpack_from('<H', fat, 14)[0], fat[16], struct.unpack_from('<I', fat, 36)[0], struct.unpack_from('<I', fat, 44)[0])
    if fat[82:87].tobytes() != b'FAT32' or geometry != (512, 1, 32, 2, 1009, 2):
        raise ValueError('Unexpected FAT32 geometry')
    macho = bytearray(boot[KERNEL_OFFSET:KERNEL_OFFSET+KERNEL_LEN])
    if len(macho) != KERNEL_LEN or sha(macho) != BASE_MACHO_SHA:
        raise ValueError('Embedded Mach-O source hash mismatch')
    return macho


def patch_sixth(b: bytearray, *, neutral: bool) -> None:
    first_opcodes = [0xD29B0009, 0xD2860009, 0xD2910009, 0xD29C0009, 0xD2870009]
    for i, (hook, original) in enumerate(HOOKS):
        p = off(b, STUBS[i]); h = off(b, hook)
        if struct.unpack_from('<I', b, h)[0] != arm_b(hook, STUBS[i]):
            raise ValueError('Unexpected MMU hook')
        w = struct.unpack_from('<21I', b, p)
        if i < 5:
            if w[0] != first_opcodes[i] or w[5:9] != (0x2881292A, SUBS, BNE, 0xD5033F9F) or w[9] != original or w[10] != arm_b(STUBS[i]+40, hook+4) or any(x != NOP for x in w[11:]):
                raise ValueError(f'Unexpected existing no-SP stub {i+1}')
    if struct.unpack_from('<I', b, off(b, 0xFFFFFFF0073F22B8))[0] != 0xD5182020:
        raise ValueError('TTBR1 opcode changed')
    if struct.unpack_from('<II', b, off(b, SCTLR)) != (0xD5181000, 0xD5033FDF):
        raise ValueError('SCTLR/ISB changed')
    p = off(b, STUBS[5]); w = struct.unpack_from('<21I', b, p)
    pre = (0xD100C3FF, 0xA9002BE9, 0xA90133EB, 0xD53B420C, 0xF90013EC)
    draw = (0xD2920009, 0xF2B70669, 0x529FE00A, 0x72BFF7EA, 0x5283840B, 0x2881292A, SUBS, BNE, 0xD5033F9F)
    post = (0xF94013EC, 0xD51B420C, 0xA94133EB, 0xA9402BE9, 0x9100C3FF)
    if w[:5] != pre or w[5:14] != draw or w[14:19] != post or w[19] != HOOKS[5][1] or w[20] != arm_b(STUBS[5]+80, HOOKS[5][0]+4):
        raise ValueError('Original SP-dependent Y528 stub changed')
    new = list(draw) + [HOOKS[5][1], arm_b(STUBS[5]+40, HOOKS[5][0]+4)] + [NOP]*10
    struct.pack_into('<21I', b, p, *new)
    if neutral:
        for address in STUBS:
            q = off(b, address)+24
            if struct.unpack_from('<II', b, q) != (SUBS, BNE):
                raise ValueError('Unexpected flags-changing loop')
            struct.pack_into('<II', b, q, SUB, CBNZ)


def patch_orange(b: bytearray) -> None:
    p = off(b, ORANGE_CAVE)
    original = (
        0xF28B27A0, 0xD100C3FF, 0xA9002BE9, 0xA90133EB, 0xD53B420C, 0xF90013EC,
        0xD28C8009, 0xF2B70329, 0x5294A00A, 0x72BFFFEA, 0x5283840B,
        0x2881292A, SUBS, BNE, 0xD5033F9F, 0xF94013EC, 0xD51B420C,
        0xA94133EB, 0xA9402BE9, 0x9100C3FF,
    )
    w = struct.unpack_from('<21I', b, p)
    if w[:20] != original or w[20] != arm_b(ORANGE_CAVE+80, SCTLR):
        raise ValueError('Unexpected SP-based orange tracer')
    if any(b[p+84:p+96]):
        raise ValueError('Orange code cave overlap')
    h = off(b, ORANGE_HOOK)
    if struct.unpack_from('<III', b, h) != (arm_b(ORANGE_HOOK, ORANGE_CAVE), 0xD5181000, 0xD5033FDF):
        raise ValueError('Original SCTLR/ISB or hook modified')
    new = [0xF28B27A0, 0xD28C8009, 0xF2B70329, 0x5294A00A, 0x72BFFFEA,
           0x5283840B, 0x2881292A, SUB, CBNZ, 0xD5033F9F,
           arm_b(ORANGE_CAVE+40, SCTLR)] + [NOP]*10
    struct.pack_into('<21I', b, p, *new)


def build(source: Path, variant: str, output_dir: Path) -> dict:
    if variant not in EXPECTED:
        raise ValueError('Unknown experiment variant')
    original = source.read_bytes()
    before = read_base(original)
    after = bytearray(before)
    patch_sixth(after, neutral=variant.endswith('b'))
    if variant.startswith('orange'):
        patch_orange(after)
    expected_macho, expected_boot, filename = EXPECTED[variant]
    if sha(after) != expected_macho:
        raise ValueError(f'Incorrect patched Mach-O: {sha(after)} != {expected_macho}')
    changes = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    allowed = set(range(off(before, STUBS[5]), off(before, STUBS[5])+84))
    if variant.endswith('b'):
        for address in STUBS[:5]:
            q = off(before, address)+24
            allowed.update(range(q, q+8))
    if variant.startswith('orange'):
        q = off(before, ORANGE_CAVE)
        allowed.update(range(q, q+84))
    if not changes or any(i not in allowed for i in changes):
        raise ValueError('Modified byte outside permitted diagnostic caves')
    if struct.unpack_from('<I', after, off(after, 0xFFFFFFF0073F22B8))[0] != 0xD5182020 or struct.unpack_from('<II', after, off(after, SCTLR)) != (0xD5181000, 0xD5033FDF):
        raise ValueError('Original native MMU system-register instructions modified')
    boot = bytearray(original)
    for pos in changes:
        boot[KERNEL_OFFSET+pos] = after[pos]
    if sha(boot) != expected_boot or sha(boot[KERNEL_OFFSET:KERNEL_OFFSET+KERNEL_LEN]) != expected_macho:
        raise ValueError('Boot image readback/hash mismatch')
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_bytes(boot)
    meta = {'variant': variant, 'base_boot_sha256': BASE_BOOT_SHA, 'boot_sha256': expected_boot,
            'base_macho_sha256': BASE_MACHO_SHA, 'macho_sha256': expected_macho,
            'boot_bytes': BOOT_LEN, 'changed_macho_bytes': len(changes),
            'edk2_and_fat_metadata_unchanged': True, 'native_ttbr1_sctlr_isb_unchanged': True,
            'mmu_enabled_on_hardware': False, 'on_device_test_required': True,
            'warning': 'HIGH-RISK, temporary fastboot boot ONLY, NEVER fastboot flash'}
    (output_dir/'MMU-AB-AUDIT.json').write_text(json.dumps(meta, indent=2)+'\n')
    (output_dir/'SHA256SUMS.txt').write_text(f'{expected_boot}  {filename}\n')
    print(json.dumps(meta, indent=2))
    return meta


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--variant', required=True, choices=tuple(EXPECTED))
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    build(a.input, a.variant, a.output_dir)

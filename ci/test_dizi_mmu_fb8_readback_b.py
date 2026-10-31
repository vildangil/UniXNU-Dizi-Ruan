#!/usr/bin/env python3
"""Source + built-image preflight for fail-closed FB8-READBACK-B.

No emulation of actual hardware framebuffer, page-table ownership or TTBR switch.
"""
import argparse
import struct
import tempfile
from pathlib import Path
import patch_dizi_mmu_fb8_readback_b as b
import patch_dizi_mmu_fb_bridge_b as base


def test_static():
    src = Path(__file__).with_name('dizi_mmu_fb8_readback_b.S.in').read_text()
    b.validate_source(src)
    # Deliberate negative cases: disallow a page-table store, missing L2 readback,
    # missing deliberate stop and unexpected native TTBR operation.
    for broken in (src.replace('ldr x20,[x19,#0x100]', 'str x5,[x19,#0x100]', 1),
                   src.replace('ldr x21,[x19,#0x1c8]', 'nop', 1),
                   src.replace('    wfe\n', '    nop\n', 1),
                   src.replace('fb8_halt:\n', 'fb8_halt:\n    tlbi vmalle1is\n', 1)):
        try:
            b.validate_source(broken)
        except ValueError:
            pass
        else:
            raise AssertionError('Unsafe diagnostic source mutation accepted')
    # Independent asm compilation without needing the source boot image:
    # the original font is SHA verified during the real build.
    payload = b.compile_tracer(src, bytes(b.FONT_BYTES))
    assert len(payload) == b.TRACER_BYTES
    assert struct.unpack_from('<I', payload)[0] & 0xfc000000 == 0x94000000
    assert b'SLOT L2 20\0' in payload and b'CODE L2 39\0' in payload
    print('PASS: FB8 source guards, four negative cases, ARM64 compile/link, no relocations')


def test_image(source: Path, output: Path):
    original = source.read_bytes()
    after = output.read_bytes()
    assert b.sha(original) == base.INPUT_BOOT
    assert len(after) == len(original)
    assert b.sha(after) == b.EXPECTED_BOOT
    old = original[base.MACHO_OFF:base.MACHO_OFF+base.MACHO_LEN]
    new = after[base.MACHO_OFF:base.MACHO_OFF+base.MACHO_LEN]
    c = base.off(new, base.CAVE)
    allowed = set(range(c,c+base.CAVE_SIZE))
    for site, original_op in base.OLD_HOOKS:
        ofs = base.off(new,site)
        allowed.update(range(ofs,ofs+4))
        expected = base.branch(site,base.CAVE) if site == base.PRE else original_op
        assert struct.unpack_from('<I',new,ofs)[0] == expected
    changed = [i for i,(a,z) in enumerate(zip(old,new)) if a!=z]
    assert changed and all(i in allowed for i in changed)
    assert after[:base.MACHO_OFF] == original[:base.MACHO_OFF]
    assert after[base.MACHO_OFF+base.MACHO_LEN:] == original[base.MACHO_OFF+base.MACHO_LEN:]
    for site in (0xfffffff0073ea10c,0xfffffff0073ea120,0xfffffff0073ea124,0xfffffff0073ea128,0xfffffff0073ea12c):
        ofs = base.off(new,site)
        assert new[ofs:ofs+4] == old[ofs:ofs+4]
    assert b'FB8 SLOT BUSY\0' in new[c:c+base.CAVE_SIZE]
    assert b'FB8 CODE DIFF\0' in new[c:c+base.CAVE_SIZE]
    assert b'FB8 BOTH DIFF\0' in new[c:c+base.CAVE_SIZE]
    # Reject a single-bit-corrupted pinned base without producing output.
    with tempfile.TemporaryDirectory() as folder:
        tmp = Path(folder)
        corrupt = bytearray(original)
        corrupt[-1] ^= 1
        (tmp/'corrupt.img').write_bytes(corrupt)
        try:
            b.build(tmp/'corrupt.img',tmp/'output.img',tmp/'audit.json')
        except ValueError as ex:
            assert 'STACK-B' in str(ex)
        else:
            raise AssertionError('Corrupted input accepted')
    print('PASS: exact source pin, hook allowlist, no native MMU edits, corrupt-input rejection')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    a = parser.parse_args()
    test_static()
    if a.input or a.output:
        if not a.input or not a.output:
            parser.error('Both --input and --output required for image tests')
        test_image(a.input,a.output)

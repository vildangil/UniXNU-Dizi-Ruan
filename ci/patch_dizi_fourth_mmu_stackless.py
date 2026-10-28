#!/usr/bin/env python3
"""Dizi XNU: modify ONLY 4th (Y480) MMU trace stub to use no SP.

Exact SHA-pinned input is the FIRST THREE stackless experimental Mach-O.
Reuse the unmodified existing 4th stub's direct-GOP drawing instructions
rather than reassembling. Preserve its original TLBI instruction in the
trampoline. No original source images, working firmware or other stages
are changed. Not proof XNU enabled the MMU.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct

SOURCE_SHA = "37ecddf974a59a8c3a74527bdd09914a6c2f67f49d71af7b00c45bc5051d3ff2"
MARKER = "DIZI_FOURTH_MMU_STAGE_STACKLESS_V1"
ENTRY = 0xFFFFFFF0073F0488
THIRD_STUB = ENTRY + 0x2A8
FOURTH_STUB = ENTRY + 0x2FC
FIFTH_STUB = ENTRY + 0x350
FOURTH_HOOK = 0xFFFFFFF0073F2308
FOURTH_ORIGINAL = 0xD508871F  # first TLBI after MAIR+ISB
TTBR1 = 0xFFFFFFF0073F22B8
SCTLR = 0xFFFFFFF0073F2350

def arm_b(frm: int, to: int) -> int:
    d = to - frm
    if d % 4 or not -(1 << 27) <= d < (1 << 27):
        raise ValueError("ARM64 B out of range")
    return 0x14000000 | ((d >> 2) & 0x3FFFFFF)

def offset(data: bytes, va: int) -> int:
    if len(data) < 4096 or struct.unpack_from("<I", data)[0] != 0xFEEDFACF:
        raise ValueError("Not Mach-O64")
    n, cmdsize = struct.unpack_from("<II", data, 16)
    if not 0 < n < 256 or cmdsize > len(data) - 32:
        raise ValueError("Invalid Mach-O commands")
    pos = 32
    for _ in range(n):
        cmd, size = struct.unpack_from("<II", data, pos)
        if size < 8 or pos + size > len(data):
            raise ValueError("Invalid command bounds")
        if cmd == 0x19:
            name, vm, vs, off, fs = struct.unpack_from("<16sQQQQ", data, pos + 8)
            if name.rstrip(b"\0") == b"__TEXT_EXEC" and vm <= va < vm + min(vs, fs):
                out = off + va - vm
                if out + 4 > len(data):
                    raise ValueError("Invalid file offset")
                return out
        pos += size
    raise ValueError("No __TEXT_EXEC file-backed VA: " + hex(va))

def patch(inp: Path, out: Path, report: Path) -> None:
    if inp.resolve() == out.resolve():
        raise ValueError("Refusing in-place modification")
    data = bytearray(inp.read_bytes())
    sha = hashlib.sha256(data).hexdigest()
    if sha != SOURCE_SHA:
        raise ValueError("Pinned 3-NOSP Mach-O SHA mismatch: " + sha)
    third, fourth, fifth = [offset(data, a) for a in (THIRD_STUB, FOURTH_STUB, FIFTH_STUB)]
    if fifth - fourth != 84 or fourth - third != 84:
        raise ValueError("Unexpected stub layout")
    if struct.unpack_from("<I", data, third)[0] != 0xD2910009:
        raise ValueError("Previously confirmed GOLD 3rd no-SP stub missing")
    if struct.unpack_from("<I", data, fourth)[0] != 0xD100C3FF:
        raise ValueError("Fourth original SP-based stub missing")
    if struct.unpack_from("<I", data, fifth)[0] != 0xD100C3FF:
        raise ValueError("Fifth original SP-based stub missing")
    hook = offset(data, FOURTH_HOOK)
    if struct.unpack_from("<I", data, hook)[0] != arm_b(FOURTH_HOOK, FOURTH_STUB):
        raise ValueError("Fourth hook unexpectedly modified")
    if struct.unpack_from("<I", data, offset(data, TTBR1))[0] != 0xD5182020:
        raise ValueError("Original TTBR1 MSR modified")
    if struct.unpack_from("<II", data, offset(data, SCTLR)) != (0xD5181000, 0xD5033FDF):
        raise ValueError("Original SCTLR/ISB modified")

    original_words = list(struct.unpack_from("<21I", data, fourth))
    if original_words[:5] != [
        0xD100C3FF, 0xA9002BE9, 0xA90133EB, 0xD53B420C, 0xF90013EC
    ]:
        raise ValueError("Original SP save sequence differs from pinned build")
    # Same nine GOP-write/barrier opcodes as in old SP-based trampoline:
    # physical 0xB82EE000, color 0xFF00FFC0, width=1600*9 pixels.
    expected_draw = [
        0xD29C0009, 0xF2B705C9, 0x529FF80A, 0x72BFE00A,
        0x5283840B, 0x2881292A, 0x7100056B, 0x54FFFFC1, 0xD5033F9F
    ]
    if original_words[5:14] != expected_draw:
        raise ValueError("Original 4th GOP draw opcodes not as expected")
    if original_words[19] != FOURTH_ORIGINAL or original_words[20] != arm_b(FOURTH_STUB + 80, FOURTH_HOOK + 4):
        raise ValueError("Original TLBI replay / branch missing")
    # Only no-SP drawing and the original displaced TLBI. The other five
    # tracing stubs and all original XNU system-register instructions stay.
    words = expected_draw + [
        FOURTH_ORIGINAL,
        arm_b(FOURTH_STUB + 40, FOURTH_HOOK + 4)
    ] + [0xD503201F] * 10
    payload = struct.pack("<21I", *words)
    assert len(payload) == 84
    old = bytes(data)
    data[fourth:fifth] = payload
    if data[:fourth] != old[:fourth] or data[fifth:] != old[fifth:]:
        raise AssertionError("Changes outside fourth stub reservation")
    differences = [i for i, (a, b) in enumerate(zip(old, data)) if a != b]
    if not differences or min(differences) < fourth or max(differences) >= fifth:
        raise AssertionError("Patch outside fourth stub")
    if struct.unpack_from("<II", data, offset(data, SCTLR)) != (0xD5181000, 0xD5033FDF):
        raise AssertionError("Original SCTLR/ISB not preserved")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    info = {
        "marker": MARKER, "source_sha256": sha,
        "patched_sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data), "modified_region_bytes": 84,
        "changed_byte_count": len(differences),
        "fourth_stub_va": hex(FOURTH_STUB), "fourth_hook_va": hex(FOURTH_HOOK),
        "returns_to": hex(FOURTH_HOOK + 4), "fourth_turquoise_y": [480,488],
        "original_tlbi_replayed": hex(FOURTH_ORIGINAL),
        "only_fourth_checkpoint_modified": True,
        "first_three_stackless_stubs_preserved": True,
        "last_two_stack_based_stubs_preserved": True,
        "native_ttbr1_sctlr_isb_untouched": True,
        "source_untouched": True, "mmu_enabled_on_hardware": False,
        "meaning": "TURQUOISE proves arrival at TLBI checkpoint after MAIR+ISB; NOT TLBI completion or MMU enable",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info, indent=2))

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    patch(a.input, a.output, a.report)

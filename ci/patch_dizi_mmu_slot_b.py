#!/usr/bin/env python3
"""Read-only pre-SCTLR L2 slot test based on SHA-pinned walk-b.

Proposed high virtual alias: 0xFFFFFFF004000000 (TTBR1 L1 C0/L2 20).
No page table modifications or post-MMU writes. Temporary fastboot boot only.
"""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

BASE_BOOT_SHA = "8c5c1aba446897a7548461a05718d79ddfb5607cfd0745c5187d423ed3a05542"
BASE_MACHO_SHA = "00e522094ba5981f3520279f5b33611cfce1aac17f1156ab2b6b6362aaa30270"
OUTPUT_BOOT_SHA = "ab1edbbc8b05fe9b59f0f6909ce84c75faf40c1c98edea6acb50d268c9e688ee"
OUTPUT_MACHO_SHA = "9e0f5f1411d674879ceedad09736e941349d487bb4836949e8a3bc51c4289662"
BOOT_SIZE = 68800512
KERNEL_OFFSET = 0x19c000 + 0x101200
KERNEL_SIZE = 51941376
CAVE = 0xfffffff0073f0988
CAVE_LENGTH = 1584
SCTLR = 0xfffffff0073f2350
READ_OFFSET = 0xf8
ORIG_LDR = 0xf940e60f   # ldr x15, [x16, #0x1c8], L2 index 39
SLOT_LDR = 0xf940820f   # ldr x15, [x16, #0x100], L2 index 20
REPLACE = (
    (b"DIZI / XNU PT WALK B", b"DIZI / XNU VA SLOT B"),
    (b"L2 DESC:", b"SLOT L2:"),
    (b"L1 INDEX C0 L2 INDEX 39", b"L1 INDEX C0 L2 INDEX 20"),
)

def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()

def offset(blob: bytes, addr: int) -> int:
    if len(blob) < 64 or struct.unpack_from("<I", blob)[0] != 0xfeedfacf:
        raise ValueError("Expected Mach-O64")
    n, total = struct.unpack_from("<II", blob, 16)
    if not 0 < n < 256 or total > len(blob) - 32:
        raise ValueError("Invalid Mach-O commands")
    pos, stop = 32, 32 + total
    for _ in range(n):
        if pos + 8 > stop:
            raise ValueError("Truncated load command")
        cmd, size = struct.unpack_from("<II", blob, pos)
        if size < 8 or pos + size > stop:
            raise ValueError("Bad load command")
        if cmd == 0x19:
            name, base, vsize, foff, fsize = struct.unpack_from("<16sQQQQ", blob, pos + 8)
            if name.rstrip(b"\0") == b"__TEXT_EXEC" and base <= addr < base + min(vsize, fsize):
                return foff + addr - base
        pos += size
    raise ValueError("Address not found in __TEXT_EXEC")

def build(source: Path, destination: Path, report: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("Refusing in-place image overwrite")
    original_boot = source.read_bytes()
    if (len(original_boot) != BOOT_SIZE or sha(original_boot) != BASE_BOOT_SHA
            or original_boot[:8] != b"ANDROID!"
            or struct.unpack_from("<I", original_boot, 40)[0] != 4):
        raise ValueError("Source is not the pinned walk-b boot v4")
    original = original_boot[KERNEL_OFFSET:KERNEL_OFFSET + KERNEL_SIZE]
    if sha(original) != BASE_MACHO_SHA:
        raise ValueError("Unexpected kernel Mach-O")
    if struct.unpack_from("<II", original, offset(original, SCTLR)) != (0xd5181000, 0xd5033fdf):
        raise ValueError("Native SCTLR and ISB changed")
    kernel = bytearray(original)
    start = offset(kernel, CAVE)
    end = offset(kernel, CAVE + CAVE_LENGTH)
    if end - start != CAVE_LENGTH:
        raise ValueError("Unexpected traced cave length")
    block = bytearray(kernel[start:end])
    if struct.unpack_from("<I", block, READ_OFFSET)[0] != ORIG_LDR:
        raise ValueError("Unexpected L2 read instruction")
    struct.pack_into("<I", block, READ_OFFSET, SLOT_LDR)
    for old, new in REPLACE:
        if len(old) != len(new) or block.count(old) != 1:
            raise ValueError("Original displayed text did not match")
        block = block.replace(old, new, 1)
    kernel[start:end] = block
    differences = [i for i, (a, b) in enumerate(zip(original, kernel)) if a != b]
    if not differences or any(i < start or i >= end for i in differences):
        raise ValueError("Unexpected edit outside existing diagnostic cave")
    result = bytearray(original_boot)
    for i in differences:
        result[KERNEL_OFFSET + i] = kernel[i]
    if sha(result) != OUTPUT_BOOT_SHA or sha(kernel) != OUTPUT_MACHO_SHA:
        raise ValueError("Output differs from locally verified image")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(result)
    record = {
        "variant": "slot-b",
        "input_boot_sha256": BASE_BOOT_SHA,
        "output_boot_sha256": OUTPUT_BOOT_SHA,
        "output_macho_sha256": OUTPUT_MACHO_SHA,
        "changed_macho_bytes": len(differences),
        "ttbr1_l1_index": "C0", "candidate_l2_index": "20",
        "candidate_alias_va": "0xFFFFFFF004000000",
        "page_table_writes": False, "post_mmu_writes": False,
        "hardware_tested": False,
        "note": "STATUS=2 plus SLOT L2=0 shows an unused entry, not a mapped framebuffer",
        "safety": "HIGH RISK: temporary fastboot boot only, never fastboot flash",
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    build(args.input, args.output, args.report)

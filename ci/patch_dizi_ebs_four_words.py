#!/usr/bin/env python3
"""Four read-only ARM64 code words from the live ExitBootServices entry.

Follows the known-good NO-XNU DarwinBoot pointer/opcode and top-tiles patches.
At y=308 four groups of eight hex digits display live instructions at
EBS+0, EBS+4, EBS+8, EBS+0x70 (the reproduced exception PC offset).
No EBS callbacks, interrupt services, memory map or XNU jump are changed.
"""
from pathlib import Path
import argparse

TARGET = "External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
MARK = "DIZI_EBS_FOUR_WORDS_V1"
GLYPH = "STATIC VOID DiziEbsPointerGlyphs ("
INSERT_AT = "    DiziEbsOpcodeGlyphs (Video,"
BOOT_CALL = "    DiziEbsPointerGlyphs (Video, (UINT64)(UINTN)gBS->ExitBootServices);"
NEW_CALL = """    // DIZI_EBS_FOUR_WORDS_V1. Actual words from live EBS code:
    // 4 x 8 hex at Y308: [0], [4], [8], [0x70].
    // Volatile reads only. 0x70 is the repeated synchronous exception delta.
    {
      volatile CONST UINT32 *EbsCode =
          (volatile CONST UINT32 *)(UINTN)gBS->ExitBootServices;
      DiziEbsWordGlyphs (Video, EbsCode[0], 0);
      DiziEbsWordGlyphs (Video, EbsCode[1], 1);
      DiziEbsWordGlyphs (Video, EbsCode[2], 2);
      DiziEbsWordGlyphs (Video, EbsCode[28], 3);
    }"""

def apply(mu: Path, dry_run: bool) -> None:
    p = mu.resolve()/TARGET
    src = p.read_text()
    if MARK in src:
        raise ValueError("Four-word fingerprint already applied")
    for marker in ("DIZI_EBS_BOUNDARY_MARKERS_V1", "DIZI_EBS_POINTER_GLYPHS_V1",
                   "DIZI_EBS_TOPTILES_BASELINE_V1", "DIZI_EBS_LIVE_OPCODE_V1"):
        if marker not in src:
            raise ValueError("Required earlier marker missing: "+marker)
    if "DarwinEnter (ArgsAddress," in src:
        raise ValueError("NO-XNU-only probe; DarwinEnter still present")
    if src.count(GLYPH) != 1 or src.count(BOOT_CALL) != 1:
        raise ValueError("pinned glyph or call anchor changed")
    start = src.index(GLYPH)
    end = src.index("\n}\n",start)+3
    helper = src[start:end]
    required = (
        "Digit < 16",
        "60 - Digit * 4",
        "X = 32 + Digit * 18 + Col * 3 + Dx;",
        "Y = 244 + Row * 3 + Dy;",
        "Video[4] < 280",
        "CONST UINT64 Video[6], UINT64 Address)"
    )
    for needle in required:
        if helper.count(needle) != 1:
            raise ValueError("missing glyph function anchor: "+needle)
    extended=helper.replace(
        "DiziEbsPointerGlyphs","DiziEbsWordGlyphs"
    ).replace(
        "CONST UINT64 Video[6], UINT64 Address)",
        "CONST UINT64 Video[6], UINT64 Address, UINTN WordIndex)"
    ).replace("Digit < 16","Digit < 8").replace(
        "60 - Digit * 4","28 - Digit * 4"
    ).replace(
        "X = 32 + Digit * 18 + Col * 3 + Dx;",
        "X = 32 + WordIndex * 176 + Digit * 18 + Col * 3 + Dx;"
    ).replace(
        "Y = 244 + Row * 3 + Dy;","Y = 308 + Row * 3 + Dy;"
    ).replace("Video[4] < 280","Video[4] < 335")
    src = src[:end]+"\n// "+MARK+"\n"+extended+src[end:]
    src = src.replace(BOOT_CALL,BOOT_CALL+"\n"+NEW_CALL,1)
    if src.count("gBS->ExitBootServices (mImage, Key)") != 1:
        raise ValueError("refusing to change ExitBootServices handoff")
    if not dry_run:
        p.write_text(src)
    print(("CHECK" if dry_run else "PATCH"),p,
          "live EBS opcode words 0,4,8,0x70 at Y308; NO-XNU")

if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    ns=ap.parse_args()
    apply(ns.mu,ns.dry_run)

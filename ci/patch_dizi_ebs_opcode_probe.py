#!/usr/bin/env python3
"""NO-XNU read-only fingerprint of the live ExitBootServices code pointer.

Applies after patch_darwinboot_ebs_stage_probe.py and
patch_dizi_ebs_pointer_glyphs.py. The first ARM64 instruction at the actual
BootServices->ExitBootServices pointer is shown as a second row of 16 hex
digits. This distinguishes the patched DXE Core PE from a different running
firmware image without changing any EBS callbacks or calling XNU.

The two rows are:
  Y=244: 64-bit runtime EBS function pointer (existing code)
  Y=276: zero-extended 32-bit instruction at that pointer (new code)
"""
from __future__ import annotations
import argparse
from pathlib import Path

SOURCE = "External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
MARK = "DIZI_EBS_LIVE_OPCODE_V1"
FUNCTION = "STATIC VOID DiziEbsPointerGlyphs ("
CALL = "    DiziEbsPointerGlyphs (Video, (UINT64)(UINTN)gBS->ExitBootServices);"
NEWCALL = """    // DIZI_EBS_LIVE_OPCODE_V1 -- read current executable memory once, before EBS.
    // The expected source-instrumented DxeCore.dll CoreExitBootServices opcode
    // at RVA 0x1434 is 0xA9BC53F3. An unequal value means this running EBS
    // pointer is NOT at that exact compiled function start.
    DiziEbsOpcodeGlyphs (Video,
      (UINT64)(*(volatile CONST UINT32 *)(UINTN)gBS->ExitBootServices));"""

def apply(mu: Path, dry_run: bool) -> None:
    p = mu.resolve() / SOURCE
    src = p.read_text()
    if MARK in src:
        raise ValueError("opcode fingerprint already applied")
    for tag in ("DIZI_EBS_BOUNDARY_MARKERS_V1",
                "DIZI_EBS_POINTER_GLYPHS_V1",
                "DIZI_EBS_TOPTILES_BASELINE_V1"):
        if tag not in src:
            raise ValueError("missing required earlier patch " + tag)
    if "DarwinEnter (ArgsAddress," in src:
        raise ValueError("refusing to fingerprint any live XNU entry")
    if src.count(FUNCTION) != 1 or src.count(CALL) != 1:
        raise ValueError("pinned glyph function or call not unique")
    start = src.index(FUNCTION)
    end = src.index("\n}\n", start) + 3
    helper = src[start:end]
    if helper.count("Y = 244 + Row * 3 + Dy;") != 1:
        raise ValueError("glyph Y anchor changed")
    if helper.count("Video[4] < 280") != 1:
        raise ValueError("glyph framebuffer bounds changed")
    opcode_helper = helper.replace(
        "DiziEbsPointerGlyphs", "DiziEbsOpcodeGlyphs"
    ).replace(
        "Y = 244 + Row * 3 + Dy;", "Y = 276 + Row * 3 + Dy;"
    ).replace("Video[4] < 280", "Video[4] < 312")
    if "DiziEbsOpcodeGlyphs" not in opcode_helper:
        raise ValueError("helper rewrite failed")
    src = src[:end] + "\n// DIZI_EBS_LIVE_OPCODE_V1: second hex line at Y276.\n" + opcode_helper + src[end:]
    src = src.replace(CALL, CALL + "\n" + NEWCALL, 1)
    if src.count("gBS->ExitBootServices (mImage, Key)") != 1:
        raise ValueError("EBS call count changed")
    if not dry_run:
        p.write_text(src)
    print(("CHECK" if dry_run else "PATCH"), p,
          "read-only runtime instruction fingerprint at Y276; no XNU entry")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args()
    apply(ns.mu, ns.dry_run)

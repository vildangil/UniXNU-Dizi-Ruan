#!/usr/bin/env python3
"""Draw dark top-bar calibration cells before NO-XNU EBS.

If baseline cells survive but no colored DXE Core stage cells do, it
distinguishes an invisible/colliding framebuffer region from a Core EBS path
that never executes our marker stores. Does not change ExitBootServices args.
"""
from __future__ import annotations
import argparse
from pathlib import Path

TARGET = "External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
MARK = "DIZI_EBS_TOPTILES_BASELINE_V1"
BOOT = "STATIC\nEFI_STATUS\nEFIAPI\nBoot ("
YELLOW = "    DiziStageMarker (Video, 0xFFFFFF00); // C YELLOW: GetMemoryMap success, entering EBS"
HELPER = """// DIZI_EBS_TOPTILES_BASELINE_V1
// 12 navy cells with white borders on DarwinBoot's proven YELLOW top band.
// CoreExitBootServices repaints only their interiors to checkpoint colors.
// Direct volatile stores only: no EFI calls, allocations or status changes.
STATIC VOID DiziEbsTopTilesBaseline (CONST UINT64 Video[6]) {
  volatile UINT32 *Fb;
  UINTN Pitch, Stage, X, Y, Left;
  if (!Video[0] || Video[5] != 32 || (Video[2] & 3) != 0 ||
      Video[3] < 900 || Video[4] < 80) { return; }
  Pitch = (UINTN)(Video[2] / 4);
  if (Pitch < Video[3]) { return; }
  Fb = (volatile UINT32 *)(UINTN)Video[0];
  for (Stage = 0; Stage < 12; ++Stage) {
    Left = 32 + Stage * 70;
    for (Y = 12; Y < 64; ++Y) {
      for (X = Left; X < Left + 48; ++X) {
        Fb[Y * Pitch + X] =
            ((Y < 16) || (Y >= 60) || (X < Left + 4) || (X >= Left + 44))
            ? 0xFFFFFFFFU : 0xFF102C50U;
      }
    }
  }
  __asm__ __volatile__ ("dsb sy" ::: "memory");
}

"""

def apply(mu: Path, dry_run: bool) -> None:
    p = mu.resolve() / TARGET
    src = p.read_text()
    if MARK in src:
        raise ValueError("already instrumented")
    if "DIZI_EBS_BOUNDARY_MARKERS_V1" not in src or "DIZI_EBS_POINTER_GLYPHS_V1" not in src:
        raise ValueError("boundary and pointer patches must precede top-tiles")
    if "DarwinEnter (ArgsAddress," in src:
        raise ValueError("Refusing any live XNU entry")
    if src.count(BOOT) != 1 or src.count(YELLOW) != 1:
        raise ValueError("pinned Boot or YELLOW anchor changed")
    src = src.replace(BOOT, HELPER + BOOT, 1)
    src = src.replace(YELLOW, YELLOW + "\n    DiziEbsTopTilesBaseline (Video);", 1)
    if src.count("gBS->ExitBootServices (mImage, Key)") != 1:
        raise ValueError("EBS call changed unexpectedly")
    if not dry_run:
        p.write_text(src)
    print(("CHECK" if dry_run else "PATCH"), p,
          "12 outlined EBS calibration tiles, no XNU entry")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    ns=ap.parse_args()
    apply(ns.mu,ns.dry_run)

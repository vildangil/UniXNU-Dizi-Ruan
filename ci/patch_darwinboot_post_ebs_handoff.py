#!/usr/bin/env python3
"""Add a post-EBS, pre-DarwinEnter marker to a *real-entry* Dizi test.

A confirmed 2026-10-28 NO-KEP hardware test showed that the real
CoreExitBootServices returns EFI_SUCCESS. For the next opt-in XNU entry,
keep the original DarwinBoot EBS/entry semantics. A magenta strip at
Y=172..195 is painted AFTER successful EBS but BEFORE DarwinEnter.
Upstream Entry.S paints Y=0..159 GREEN *inside* DarwinEnter before the MMU
shutdown and branch. The two bands distinguish milestones, neither is
proof of execution of an XNU instruction.

Only reusable volatile stores: NO BootServices calls after EBS.
"""
from __future__ import annotations
import argparse
from pathlib import Path

TARGET = "External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
MARK = "DIZI_XNU_POST_EBS_MARK_V1"
FUNC = """STATIC
EFI_STATUS
EFIAPI
Boot ("""
ANCHOR = """    if (!EFI_ERROR (Status)) {
      DarwinEnter (ArgsAddress, Address + Kernel.Entry - Kernel.Base, Address, WindowSize, Video[0], Video[2] * Video[4]);
      CpuDeadLoop ();
    }"""

HELPER = """// DIZI_XNU_POST_EBS_MARK_V1
// Retained magenta Y=172..195 after REAL EFI ExitBootServices succeeded.
// The upstream DarwinEnter assembly's GREEN stripe covers Y=0..159.
// Both distinguish firmware milestones only, not confirmed XNU execution.
STATIC VOID DiziPostEbsMark (CONST UINT64 Video[6]) {
  volatile UINT32 *Frame;
  UINTN X, Y, Pitch, MaxX;
  if (Video[0] == 0 || Video[5] != 32 || Video[2] < 4 ||
      (Video[2] & 3) != 0 || Video[4] < 205 || Video[3] < 900) {
    return;
  }
  Pitch = (UINTN)(Video[2] / 4);
  if (Pitch < Video[3]) { return; }
  Frame = (volatile UINT32 *)(UINTN)Video[0];
  MaxX = 900;
  for (Y = 172; Y < 196; ++Y) {
    for (X = 0; X < MaxX; ++X) {
      Frame[Y * Pitch + X] = 0xFFFF00FFU;
    }
  }
  __asm__ __volatile__ ("dsb sy" ::: "memory");
}

"""

def apply(mu: Path, dry_run: bool) -> None:
    p=mu.resolve()/TARGET
    source=p.read_text()
    if MARK in source:
        raise ValueError("Post EBS marker already applied")
    if "DIZI_XNU_REAL_FIRST_ENTRY_V1" not in source:
        raise ValueError("First apply the pinned real-entry patch")
    if any(m in source for m in ("DIZI_EBS_BOUNDARY_MARKERS_V1",
                                 "DIZI_ADT_PARSE_PROBE_FAIL_CLOSED_V1")):
        raise ValueError("Do not combine with NO-XNU/EBS-abort patches")
    if source.count(FUNC)!=1 or source.count(ANCHOR)!=1:
        raise ValueError("Pinned EBS success or Boot anchor changed")
    if source.count("gBS->ExitBootServices (mImage, Key)")!=1:
        raise ValueError("EBS call changed")
    source=source.replace(FUNC,HELPER+FUNC,1)
    source=source.replace(ANCHOR,ANCHOR.replace(
        "      DarwinEnter (", "      DiziPostEbsMark (Video);\n      DarwinEnter ("),1)
    if source.count("DarwinEnter (ArgsAddress,")!=1 or source.count("DiziPostEbsMark (Video);")!=1:
        raise ValueError("Real kernel-entry path damaged")
    if not dry_run:
        p.write_text(source)
    print(("CHECK" if dry_run else "PATCH"), p,
          "real EBS success => Y172 MAGENTA => DarwinEnter GREEN; kernel unverified")

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a=ap.parse_args()
    apply(a.mu,a.dry_run)

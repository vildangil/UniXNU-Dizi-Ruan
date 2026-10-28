#!/usr/bin/env python3
"""Dizi-only pointer telemetry for the EBS boundary NO-XNU experiment.

Applies after patch_darwinboot_ebs_stage_probe.py. Shows the *runtime*
gBS->ExitBootServices entry address as 16 hexadecimal digits on the existing
GOP framebuffer (Y=244..264). No EFI calls, allocations, callbacks or changes
to the handoff. The prior yellow marker and 12 DXE Core stripes remain.
"""
from __future__ import annotations

import argparse
from pathlib import Path

SOURCE = "External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
MARK = "DIZI_EBS_POINTER_GLYPHS_V1"
CALL = "    DiziStageMarker (Video, 0xFFFFFF00); // C YELLOW: GetMemoryMap success, entering EBS"
BOOT = "STATIC\nEFI_STATUS\nEFIAPI\nBoot ("

HELPER = r'''
// DIZI_EBS_POINTER_GLYPHS_V1
// 16 hex digits at Y=244, x=32..319; white on navy background.
// This reports the *runtime* BootServices EBS pointer; pair the address with
// DxeCore.map/DxeCore.efi and the exception PC to derive the module load base.
// This uses no BootServices, pool allocation, protocol lookup, or Print().
STATIC VOID DiziEbsPointerGlyphs (CONST UINT64 Video[6], UINT64 Address) {
  STATIC CONST UINT8 Font[16][7] = {
    {14,17,19,21,25,17,14}, // 0
    {4,12,4,4,4,4,14},      // 1
    {14,17,1,2,4,8,31},     // 2
    {30,1,1,14,1,1,30},     // 3
    {2,6,10,18,31,2,2},     // 4
    {31,16,16,30,1,1,30},   // 5
    {14,16,16,30,17,17,14}, // 6
    {31,1,2,4,8,8,8},       // 7
    {14,17,17,14,17,17,14}, // 8
    {14,17,17,15,1,1,14},  // 9
    {14,17,17,31,17,17,17},// A
    {30,17,17,30,17,17,30},// B
    {14,17,16,16,16,17,14},// C
    {30,17,17,17,17,17,30},// D
    {31,16,16,30,16,16,31},// E
    {31,16,16,30,16,16,16} // F
  };
  volatile UINT32 *Fb;
  UINTN Pitch, Digit, Row, Col, Dy, Dx, Nibble, X, Y;
  if (!Video[0] || Video[5] != 32 || (Video[2] & 3) != 0 ||
      Video[3] < 340 || Video[4] < 280) {
    return;
  }
  Pitch = (UINTN)(Video[2] / 4);
  if (Pitch < Video[3]) { return; }
  Fb = (volatile UINT32 *)(UINTN)Video[0];
  for (Digit = 0; Digit < 16; ++Digit) {
    Nibble = (UINTN)((Address >> (60 - Digit * 4)) & 15ULL);
    for (Row = 0; Row < 7; ++Row) {
      for (Col = 0; Col < 6; ++Col) {
        UINT32 Pixel = (Col < 5 && ((Font[Nibble][Row] >> (4-Col)) & 1))
                         ? 0xFFFFFFFFU : 0xFF002050U;
        for (Dy = 0; Dy < 3; ++Dy) {
          for (Dx = 0; Dx < 3; ++Dx) {
            X = 32 + Digit * 18 + Col * 3 + Dx;
            Y = 244 + Row * 3 + Dy;
            Fb[Y * Pitch + X] = Pixel;
          }
        }
      }
    }
  }
  __asm__ __volatile__ ("dsb sy" ::: "memory");
}
'''

def apply(mu: Path, dry_run: bool) -> None:
    target = mu.resolve() / SOURCE
    src = target.read_text()
    if MARK in src:
        raise ValueError("pointer telemetry already present")
    if "DIZI_EBS_BOUNDARY_MARKERS_V1" not in src:
        raise ValueError("first apply the NO-XNU DarwinBoot EBS boundary patch")
    if src.count(CALL) != 1 or src.count(BOOT) != 1:
        raise ValueError("pinned DarwinBoot EBS/Boot anchor changed")
    if "DarwinEnter (ArgsAddress," in src:
        raise ValueError("refusing to instrument a live XNU entry")
    src = src.replace(BOOT, HELPER + "\n" + BOOT, 1)
    src = src.replace(CALL,
        "    DiziEbsPointerGlyphs (Video, (UINT64)(UINTN)gBS->ExitBootServices);\n"
        + CALL, 1)
    assert src.count("DiziEbsPointerGlyphs (Video,") == 1
    if not dry_run:
        target.write_text(src)
    print(("CHECK" if dry_run else "PATCH"), target,
          "EBS runtime pointer hex glyphs, no XNU handoff")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mu", type=Path)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    apply(args.mu, args.dry_run)

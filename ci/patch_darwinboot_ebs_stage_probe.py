#!/usr/bin/env python3
"""Dizi EBS boundary localization, NOT an XNU entry and NOT a bootable OS.

Direct pixel markers stage the last EFI calls without allocating after the
final GetMemoryMap; after successful ExitBootServices, halt with WFE loop.
This diagnostic deliberately does not execute DarwinEnter or XNU.
"""
from __future__ import annotations
import argparse
from pathlib import Path

SOURCE="External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
TAG="DIZI_EBS_BOUNDARY_MARKERS_V1"

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mu",type=Path)
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args()
    path=args.mu.resolve()/SOURCE
    src=path.read_text()
    if TAG in src or "DIZI_WINDOW_ALLOCATION_PROBE_V1" in src or "DIZI_XNU_REAL_FIRST_ENTRY_V1" in src:
        raise RuntimeError("Boundary diagnostic cannot be combined with any other handoff patch")
    targets={
       "  DEBUG ((DEBUG_ERROR, \"\\fDARWINBOOT: hand-off to the kernel\\n\\n\"));":
        "  DiziStageMarker (Video, 0xFF0077FF); // A BLUE: prior to DEBUG diagnostics\n",
       "  for (Attempt = 0; Attempt < 3; Attempt++) {":
        "  DiziStageMarker (Video, 0xFF00FFFF); // B CYAN: EFI DEBUG code completed\n",
       "    Status = gBS->ExitBootServices (mImage, Key);":
        "    DiziStageMarker (Video, 0xFFFFFF00); // C YELLOW: GetMemoryMap success, entering EBS\n",
    }
    for anchor,insert in targets.items():
        if src.count(anchor)!=1: raise RuntimeError(f"Pinned DarwinBoot anchor missing: {anchor!r}")
        src=src.replace(anchor,insert+anchor,1)
    old="""    if (!EFI_ERROR (Status)) {
      DarwinEnter (ArgsAddress, Address + Kernel.Entry - Kernel.Base, Address, WindowSize, Video[0], Video[2] * Video[4]);
      CpuDeadLoop ();
    }
    if (Status != EFI_INVALID_PARAMETER) { CpuDeadLoop (); }"""
    new="""    if (!EFI_ERROR (Status)) {
      DiziStageMarker (Video, 0xFFFF00FF); // D MAGENTA: EBS returned EFI_SUCCESS
      // EBS succeeded: deliberately NO DarwinEnter / XNU branch.
      CpuDeadLoop ();
    }
    if (Status != EFI_INVALID_PARAMETER) {
      DiziStageMarker (Video, 0xFFFF0000); // RED: unexpected EBS error
      CpuDeadLoop ();
    }"""
    if src.count(old)!=1: raise RuntimeError("Cannot match exact EBS success/failure path")
    src=src.replace(old,new,1)
    marker="""
 // DIZI_EBS_BOUNDARY_MARKERS_V1
 // Draw a thin 80-pixel stage band with direct volatile framebuffer stores.
 // Do not use EFI/BS calls or allocate once the final memory map is obtained.
 // BLUE before debug; CYAN after debug; YELLOW immediately before ExitBootServices;
 // MAGENTA after ExitBootServices returned success; RED unexpected EBS error.
 STATIC VOID DiziStageMarker (CONST UINT64 Video[6], UINT32 Color) {
   volatile UINT32 *Fb;
   UINTN X, Y, MaxX, MaxY, Pitch;
   if (!Video[0] || Video[5] != 32 || Video[2] < 4 ||
       Video[3] == 0 || Video[4] == 0) { return; }
   Pitch = (UINTN)(Video[2] / 4);
   MaxX = MIN ((UINTN)Video[3], (UINTN)1200);
   MaxY = MIN ((UINTN)Video[4], (UINTN)80);
   if (Pitch < MaxX) { return; }
   Fb = (volatile UINT32 *)(UINTN)Video[0];
   for (Y = 0; Y < MaxY; ++Y) {
     for (X = 0; X < MaxX; ++X) {
       Fb[Y * Pitch + X] = Color;
     }
   }
   __asm__ volatile ("dsb sy" ::: "memory");
 }
"""
    anchor="STATIC\nEFI_STATUS\nEFIAPI\nBoot ("
    if src.count(anchor)!=1: raise RuntimeError("Cannot insert safe stage helper")
    src=src.replace(anchor,marker+"\n"+anchor,1)
    if src.count("DarwinEnter (ArgsAddress,")!=0:
        raise RuntimeError("Unsafe: DarwinEnter call still present in stage-only build")
    if src.count("gBS->ExitBootServices (mImage, Key)")!=1:
        raise RuntimeError("Exactly one EBS attempt required")
    if not args.dry_run:
        path.write_text(src)
    print(("CHECK" if args.dry_run else "PATCH"),path)
    print("BLUE->CYAN->YELLOW->MAGENTA or exception, XNU entry never attempted")

if __name__=="__main__":
    main()

#!/usr/bin/env python3
"""Instrument Dizi UEFI DXE Core ExitBootServices with framebuffer tiles.

Diagnose the actual EBS stage that faults on SM7435. Never changes normal
firmware or other probes; only a disposable Mu-Silicium build checkout.
EFI Core source fixed to microsoft/mu_basecore gitlink bb557081....
NO XNU ENTRY: pair exclusively with ci/patch_darwinboot_ebs_stage_probe.py.
"""
from __future__ import annotations

import argparse
from pathlib import Path

SOURCE = "Mu_Basecore/MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c"
MARK = "DIZI_DXE_CORE_EBS_STAGES_V1"
# Address / stride are read from verified dizi bootloader video diagnostic:
# "video base=0xB0000000 display=1 row=6400 width=1600 height=2560 depth=32"
FB = 0xB0000000
PITCH = 1600
STAGES = [
    ("  if (!mExitBootServicesCalled) {",
     "A", "0xFF0000FF", "entry into DXE Core ExitBootServices"),
    ("  // Disable Timer", "B", "0xFF00FF00", "BeforeExitBootServices notification finished"),
    ("  // Terminate memory services if the MapKey matches",
     "C", "0xFFFFFF00", "timer shutdown finished"),
    ("  gMemoryMapTerminated = TRUE;",
     "D", "0xFF00FFFF", "CoreTerminateMemoryMap succeeded"),
    ("  // Report that ExitBootServices() has been called",
     "E", "0xFFFF8800", "ExitBootServices callbacks finished"),
    ("  MemoryProtectionExitBootServicesCallback ();",
     "F", "0xFFAA00FF", "about to run memory-protection callback"),
    ("  // Disable CPU Interrupts", "G", "0xFFFFFFFF", "memory-protection and debug timer done"),
    ("  // Clear the non-runtime values of the EFI System Table",
     "H", "0xFF44FF44", "interrupts disabled"),
]

# Keep marker routines independent of boot services and memory allocations.
MARKER = """
// DIZI_DXE_CORE_EBS_STAGES_V1
// Board-specific diagnostic ONLY. 8 tiles * 160 pixels wide * 44 high.
// IMPORTANT: tile is emitted BEFORE each corresponding step. An exception
// will leave the last completed tile on screen.
STATIC VOID
DiziDxeEbsTile (
  IN UINTN Index,
  IN UINT32 Color
  )
{
  volatile UINT32 *Fb = (volatile UINT32 *)(UINTN)0xB0000000ULL;
  UINTN X, Y, X0;
  if (Index >= 8) { return; }
  X0 = Index * 160;
  for (Y = 0; Y < 44; ++Y) {
    for (X = 0; X < 160; ++X) {
      Fb[Y * 1600 + X0 + X] = Color;
    }
  }
  __asm__ volatile ("dsb sy" ::: "memory");
}

"""

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mu", type=Path)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    file = args.mu.resolve() / SOURCE
    text = file.read_text()
    if MARK in text:
        raise RuntimeError("DXE core instrumented twice")
    boundary = "EFI_STATUS\nEFIAPI\nCoreExitBootServices (\n  IN EFI_HANDLE  ImageHandle,"
    if text.count(boundary) != 1:
        raise RuntimeError("Pinned DXE Core ExitBootServices function changed")
    before, body = text.split(boundary, 1)
    end = body.index("\n/**")
    method, after = body[:end], body[end:]
    for anchor, ch, color, desc in STAGES:
        if method.count(anchor) != 1:
            raise RuntimeError(f"EBS stage anchor not unique: {ch}: {anchor}")
        method = method.replace(anchor, f"  DiziDxeEbsTile ({ord(ch)-ord('A')}, {color}); // {ch}: {desc}\n"+anchor, 1)
    if "gBS = NULL;" not in method:
        raise RuntimeError("DXE Core gBS exit invariant missing")
    # Add final tile once the boot services table is gone, before return.
    final_anchor = "  gRuntime->AtRuntime = TRUE;"
    if method.count(final_anchor) != 1:
        raise RuntimeError("DXE Core runtime marker missing")
    method = method.replace(final_anchor, "  // UEFI DXE Core about to leave ExitBootServices successfully.\n"
       + final_anchor + "\n  DiziDxeEbsTile (7, 0xFF44FF44); // H success (last duplicate overlay)\n", 1)
    # H is emitted above pre-ST zeroing; a second H overlay is redundant.
    # The 8 colored tiles are enough to localize the exception.
    out = before + MARKER + boundary + method + after
    if out.count("DiziDxeEbsTile (") != len(STAGES)+2:
        raise RuntimeError("Unexpected marker count")
    if not args.dry_run:
        file.write_text(out)
    print(("CHECK" if args.dry_run else "PATCH") + " DXE Core EBS stages: " + str(file))
    for i, (_, marker, color, desc) in enumerate(STAGES):
        print(f"{marker} {color} - {desc}")
    print("No XNU entry or BootServices fallback here.")

if __name__ == "__main__":
    main()

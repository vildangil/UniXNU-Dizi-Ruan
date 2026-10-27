#!/usr/bin/env python3
"""Dizi UEFI allocation probe: never exits boot services or enters XNU.

Inserted *after* DarwinBoot successfully reads kernel and ADT, and only
after AllocateWindow returns success. On exit DarwinBoot's Fail path
releases all allocations; it does not write kernel code into them.
Test firmware remains temporary fastboot boot; no flash/update.
"""
from __future__ import annotations
import argparse
from pathlib import Path

SRC = "External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
ANCHOR = "  ArgsAddress = ALIGN_VALUE (Address + Kernel.End - Kernel.Base, SIZE_16KB);"
MARK = "DIZI_WINDOW_ALLOCATION_PROBE_V1"

def patch(root: Path, dry_run: bool = False):
    file = root.resolve() / SRC
    src = file.read_text()
    if MARK in src:
        raise ValueError("Already patched")
    if src.count(ANCHOR) != 1:
        raise ValueError("Pinned DarwinBoot window checkpoint changed")
    addition = """  // DIZI_WINDOW_ALLOCATION_PROBE_V1: validate EFI memory allocation
  // and the kernel address window, then deliberately return to UniXNU.
  // This patch must never allocate/write a kernel executable or exit EFI.
  Print (L"DIZI: KERNEL WINDOW OK addr=%lx bytes=%lx (NO XNU ENTRY)\\n",
         Address, WindowSize);
  DiagDraw (L"DIZI: UEFI RAM WINDOW OK / XNU NOT RUNNING", 0);
  gBS->Stall (1500000);
  Status = EFI_ABORTED;
  goto Fail;
"""
    src = src.replace(ANCHOR, addition + ANCHOR, 1)
    if not dry_run:
        file.write_text(src)
    print(("CHECK " if dry_run else "PATCH ") + str(file))

if __name__ == "__main__":
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("mu", type=Path)
    arg.add_argument("--dry-run", action="store_true")
    a = arg.parse_args()
    patch(a.mu, a.dry_run)

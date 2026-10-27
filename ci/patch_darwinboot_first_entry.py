#!/usr/bin/env python3
"""Minimal user-authorized *real* DarwinBoot -> XNU first-entry diagnostic.

Only the disposable GitHub Actions DarwinBoot checkout is modified.
Must NOT be applied to the working firmware or RAM-check probes.
There is deliberately NO abort: original ExitBootServices + DarwinEnter
execute after the explicit UniXNU entry confirmation.
No automatic menu selection, no flash, no watchdog/reset loop.
"""
from __future__ import annotations
import argparse
from pathlib import Path

SOURCE="External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
ANCHOR='  Print (L"DARWINBOOT: inputs validated; exiting boot services\\n");'
MARK="DIZI_XNU_REAL_FIRST_ENTRY_V1"

def patch(mu:Path, dry_run:bool=False):
    src=mu.resolve()/SOURCE
    s=src.read_text()
    if MARK in s:
        raise ValueError("real-entry patch already installed")
    if s.count(ANCHOR)!=1:
        raise ValueError("Pinned DarwinBoot changed: no unique pre-handoff marker")
    if "DIZI_WINDOW_ALLOCATION_PROBE_V1" in s or "DIZI_ADT_PARSE_PROBE_FAIL_CLOSED_V1" in s:
        raise ValueError("Refusing to stack real-entry on fail-closed RAM/ADT probe")
    if s.count("gBS->ExitBootServices (mImage, Key)")!=1 or s.count("DarwinEnter (ArgsAddress,")!=1:
        raise ValueError("Pinned original DarwinEnter/ExitBootServices entry path changed")
    if s.count("if (Used > WindowSize - BLOCK_SIZE)")!=1:
        raise ValueError("Pre-entry Mach-O memory sizing check changed")
    replacement="""  // DIZI_XNU_REAL_FIRST_ENTRY_V1
  // Diagnostic one-time screen before the irreversible transition.
  // EFI remains available here; after ExitBootServices it cannot return.
  // Device RAM FDT ownership and Apple ABI compatibility are NOT validated.
  Print (L"DIZI XNU FIRST ENTRY: stopping UEFI; NO AUTO RESTART\\\\n");
  DiagDraw (L"XNU FIRST ENTRY: EXIT EFI / NO RETURN", 0);
  DiagDraw (L"GREEN TOP BAR = DARWINENTER, NOT PROOF XNU BOOTED", 1);
  gBS->Stall (2000000);
"""
    out=s.replace(ANCHOR,replacement+ANCHOR,1)
    if not dry_run:
        src.write_text(out)
    print(("CHECK " if dry_run else "PATCH ")+str(src))
    print("Real entry requested; ExitBootServices and DarwinEnter remain enabled.")

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    args=ap.parse_args()
    patch(args.mu,args.dry_run)

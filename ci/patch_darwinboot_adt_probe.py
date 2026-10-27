#!/usr/bin/env python3
"""Fail closed after DarwinBoot parses an experimental Dizi ADT.

Test loader, Mach-O and ADT parsing without exiting EFI boot services,
allocating a kernel window, or entering unprelinked XNU.
Only intended for a probe build in a temporary Mu-Silicium checkout.
"""
from __future__ import annotations
import argparse
from pathlib import Path

MARK="DIZI_ADT_PARSE_PROBE_FAIL_CLOSED_V1"
SRC="External/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c"
ANCHOR="  Status = ReadBootVideo (Video);"

def apply(mu:Path, dry_run=False):
    target=mu.resolve()/SRC
    s=target.read_text()
    if MARK in s:
        raise RuntimeError("ADT probe patch already applied")
    if s.count(ANCHOR)!=1:
        raise RuntimeError("DarwinBoot version changed; cannot patch safely")
    code='''  // DIZI_ADT_PARSE_PROBE_FAIL_CLOSED_V1.
  // Reaching here means Mach-O and ADT were parsed by the official loader,
  // and optional files were checked. A source-only XNU is NOT safe to enter.
  Print (L"DARWINBOOT: DIZI ADT accepted; prelink absent; entry BLOCKED\\\\n");
  Status = EFI_ABORTED;
  goto Fail;

'''
    s=s.replace(ANCHOR, code+ANCHOR, 1)
    if not dry_run: target.write_text(s)
    print(("CHECK " if dry_run else "PATCH ")+str(target))
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mu",type=Path)
    p.add_argument("--dry-run",action="store_true")
    a=p.parse_args()
    apply(a.mu,a.dry_run)

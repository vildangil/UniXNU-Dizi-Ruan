#!/usr/bin/env python3
"""Correct the *diagnostic-only* DXE Core framebuffer base on dizi.

Photo 2026-10-28: DarwinBoot's LIVE GOP debug output reports
video base=0xB8000000, row=6400, width=1600, height=2560, depth=32.
Prior DXE Core visual instrumentation incorrectly assumed 0xB0000000.
Keep this correction confined to the disposable Mu_Basecore CI checkout.
Do not touch normal EDK2 or any EBS memory/timer/event semantics.
"""
from __future__ import annotations
import argparse
from pathlib import Path

TARGET="Mu_Basecore/MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c"
MARK="DIZI_DXE_CORE_EBS_FB_BASE_B800_V1"
OLD="Fb = (volatile UINT32 *)(UINTN)0xB0000000ULL;"
NEW="Fb = (volatile UINT32 *)(UINTN)0xB8000000ULL;"

def apply(mu: Path, dry_run: bool) -> None:
    p=mu.resolve()/TARGET
    src=p.read_text()
    if MARK in src:
        raise ValueError("framebuffer correction already applied")
    if "DIZI_DXE_CORE_EBS_TRACE_V1" not in src or "DIZI_DXE_CORE_EBS_TOPTILES_V1" not in src:
        raise ValueError("Apply existing 12-stage trace and top-tile layout first")
    if src.count(OLD)!=1 or NEW in src:
        raise ValueError("Expected exactly one old DxeCore framebuffer literal")
    src=src.replace(OLD,NEW+"  // "+MARK,1)
    if sum(src.count(f"DiziCoreEbsMark ({stage},") for stage in range(12))!=12:
        raise ValueError("12 EBS stage marks must remain intact")
    if src.count("CoreNotifySignalList (&gEfiEventBeforeExitBootServicesGuid);")!=1:
        raise ValueError("BeforeExitBootServices handler modified unexpectedly")
    if src.count("CoreNotifySignalList (&gEfiEventExitBootServicesGuid);")!=1:
        raise ValueError("ExitBootServices handler modified unexpectedly")
    if not dry_run:
        p.write_text(src)
    print(("CHECK" if dry_run else "PATCH"),p,
          "DXE EBS visual diagnostics base B8000000 verified from live GOP")

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    a=ap.parse_args()
    apply(a.mu,a.dry_run)

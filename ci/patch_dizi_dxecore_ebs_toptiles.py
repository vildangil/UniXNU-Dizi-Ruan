#!/usr/bin/env python3
"""Replace only the layout of the NO-XNU DXE Core EBS stage markers.

The old 12 bands (Y=84..228) may be overwritten by the menu/error painter.
Relocate the same 12 source-level checkpoints to persistent cells inside the
wide yellow boundary bar (Y=16..59). All original EBS callbacks remain.
"""
from __future__ import annotations
import argparse
from pathlib import Path

PATH = "Mu_Basecore/MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c"
MARK = "DIZI_DXE_CORE_EBS_TOPTILES_V1"
OLD = """  for (Y = 84 + Stage * 12; Y < 84 + (Stage + 1) * 12; ++Y) {
    for (X = 0; X < 960; ++X) {
      Fb[Y * 1600 + X] = Color;
    }
  }"""
NEW = """  // DIZI_DXE_CORE_EBS_TOPTILES_V1: 12 retained color cells
  // X = 32 + 70*stage, top yellow strip Y = 16..59; border remains.
  for (Y = 16; Y < 60; ++Y) {
    for (X = 36 + Stage * 70; X < 76 + Stage * 70; ++X) {
      Fb[Y * 1600 + X] = Color;
    }
  }"""

def apply(mu: Path, dry_run: bool) -> None:
    p = mu.resolve() / PATH
    src = p.read_text()
    if "DIZI_DXE_CORE_EBS_TRACE_V1" not in src:
        raise ValueError("Apply the existing 12-stage trace first")
    if MARK in src:
        raise ValueError("Top tile patch already applied")
    if src.count(OLD) != 1:
        raise ValueError("Expected pinned DXE Core framebuffer loop not found")
    patched = src.replace(OLD, NEW, 1)
    for stage in range(12):
        if patched.count(f"DiziCoreEbsMark ({stage},") != 1:
            raise ValueError(f"Missing EBS stage {stage}")
    if patched.count("CoreNotifySignalList (&gEfiEventExitBootServicesGuid);") != 1:
        raise ValueError("ExitBootServices callback was unexpectedly modified")
    if not dry_run:
        p.write_text(patched)
    print(("CHECK" if dry_run else "PATCH"), p,
          "12 retained top-bar tiles, no EBS callback modifications")

if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    ns=ap.parse_args()
    apply(ns.mu,ns.dry_run)

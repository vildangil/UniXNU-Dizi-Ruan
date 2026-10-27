#!/usr/bin/env python3
"""Add the official DarwinBoot XNU loader only in a CI checkout of Mu dizi.

The known-working EDK2 image and main UEFI build script are not modified.
DarwinBoot source is pinned externally; this patch does not supply a
prelinked kernel, ADT or working XNU handoff.
"""
from __future__ import annotations
import argparse
from pathlib import Path

MOD = "DarwinBootPkg/Driver/DarwinBoot.inf"
MARK = "DIZI_DARWINBOOT_PROBE_V1"

def unique_replace(content: str, before: str, after: str, where: str) -> str:
    count = content.count(before)
    if count != 1:
        raise ValueError(f"{where}: expected exactly one anchor, found {count}")
    return content.replace(before, after, 1)

def patch(root: Path, dry_run: bool) -> None:
    root = root.resolve()
    driver = root / "External/DarwinBoot" / MOD
    if not driver.is_file():
        raise FileNotFoundError(f"Pinned DarwinBoot unavailable at {driver}")
    targets = {
        "dev": root / "Platforms/Xiaomi/diziPkg/DeviceBuild.py",
        "dsc": root / "Platforms/Xiaomi/diziPkg/dizi.dsc",
        "fdf": root / "Platforms/Xiaomi/diziPkg/dizi.fdf",
    }
    data = {k: v.read_text() for k, v in targets.items()}
    if any(MARK in v for v in data.values()):
        raise ValueError("DarwinBoot probe integration already present")
    if "DIZI_PUBLIC_UNIXNU_V1" not in data["dev"]:
        raise ValueError("Apply base UniXNU integration first")
    data["dev"] = unique_replace(
        data["dev"], '"External/UniXNU/package",  # DIZI_PUBLIC_UNIXNU_V1',
        '"External/UniXNU/package",  # DIZI_PUBLIC_UNIXNU_V1\n'
        '        "External/DarwinBoot",  # DIZI_DARWINBOOT_PROBE_V1',
        "add DarwinBoot package lookup",
    )
    data["dsc"] = unique_replace(
        data["dsc"], f"  UniXNUPkg/Application/UniXNU/UniXNU.inf\n",
        f"  UniXNUPkg/Application/UniXNU/UniXNU.inf\n"
        f"  {MOD}  # {MARK}\n",
        "DSC firmware component",
    )
    data["fdf"] = unique_replace(
        data["fdf"], "  INF UniXNUPkg/Application/UniXNU/UniXNU.inf\n",
        f"  INF UniXNUPkg/Application/UniXNU/UniXNU.inf\n"
        f"  INF {MOD}  # {MARK}\n",
        "FDF UEFI driver",
    )
    for k, p in targets.items():
        if not dry_run:
            p.write_text(data[k])
        print(("CHECK " if dry_run else "PATCH ") + str(p.relative_to(root)))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    patch(a.mu, a.dry_run)

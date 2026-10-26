#!/usr/bin/env python3
"""Integrate *public upstream* UniXNU into pinned Mu-Silicium dizi EDK2.

This works on an isolated checkout during GitHub Actions; never modifies
the Mu-Silicium source repository or the board profile in Git.
No private repos, prebuilt Mach-O, vendor firmware or address guesses.
"""
from __future__ import annotations

import argparse
from pathlib import Path

DSC_INFS = (
    "UniXNUPkg/Application/UniXNU/UniXNU.inf",
    "UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf",
    "UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf",
)


def replace_once(text: str, before: str, after: str, label: str) -> str:
    found = text.count(before)
    if found != 1:
        raise ValueError(f"{label}: expected one anchor, found {found}")
    return text.replace(before, after, 1)


def patch(mu: Path, dry_run: bool = False) -> None:
    mu = mu.resolve()
    package = mu / "External/UniXNU/package/UniXNUPkg"
    if not (package / "UniXNUPkg.dec").is_file():
        raise FileNotFoundError("Checkout public UniXNU/package before integration")
    dev = mu / "Platforms/Xiaomi/diziPkg/DeviceBuild.py"
    dsc = mu / "Platforms/Xiaomi/diziPkg/dizi.dsc"
    fdf = mu / "Platforms/Xiaomi/diziPkg/dizi.fdf"
    paths = {p: p.read_text() for p in (dev, dsc, fdf)}
    if any("DIZI_PUBLIC_UNIXNU_V1" in s for s in paths.values()):
        raise ValueError("Already integrated")

    devtext = replace_once(
        paths[dev],
        '        "Silicon/Silicium",\n',
        '        "Silicon/Silicium",\n'
        '        "External/UniXNU/package",  # DIZI_PUBLIC_UNIXNU_V1\n',
        "Mu package search path",
    )
    dsctext = replace_once(
        paths[dsc],
        "[LibraryClasses]\n",
        "[LibraryClasses]\n"
        "  # DIZI_PUBLIC_UNIXNU_V1, public upstream firmware library\n"
        "  UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf\n",
        "dizi library mapping",
    )
    dsctext = replace_once(
        dsctext,
        "[Components]\n",
        "[Components]\n"
        + "".join(f"  {inf}\n" for inf in DSC_INFS),
        "dizi source modules",
    )
    # Insert in FVMAIN (NOT FVMAIN_COMPACT and NOT APRIORI). The public
    # UniXNU DXE driver handles registering the application Boot#### entry.
    fdftxt = replace_once(
        paths[fdf],
        "  !include Include/DXE.inc\n",
        "  !include Include/DXE.inc\n"
        "  # DIZI_PUBLIC_UNIXNU_V1: stock UniXNU app and read-only RAM disk\n"
        + "".join(f"  INF {inf}\n" for inf in DSC_INFS),
        "Dizi FVMAIN insert",
    )
    updated = {dev: devtext, dsc: dsctext, fdf: fdftxt}
    for path, text in updated.items():
        if not dry_run:
            path.write_text(text)
        print(("CHECK " if dry_run else "PATCH ") + str(path.relative_to(mu)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mu", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    patch(args.mu, args.dry_run)


if __name__ == "__main__":
    main()

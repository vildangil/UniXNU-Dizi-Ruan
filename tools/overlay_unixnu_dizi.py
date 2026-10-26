#!/usr/bin/env python3
"""Opt-in UniXNU/DarwinBoot firmware integration for Redmi Pad Pro (dizi).

Modifies a COPY of the Mu-Silicium source tree, not a boot image or any device.
The script only wires the firmware boot chain. It does NOT supply an XNU kernel,
a FAT payload, an iPadOS userland, or a proven on-device boot.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

DSC = Path("Platforms/Xiaomi/diziPkg/dizi.dsc")
FDF = Path("Platforms/Xiaomi/diziPkg/dizi.fdf")
SEC = Path("Silicon/Silicium/SiliciumPkg/Sec/Sec.c")
SEC_ASM = Path("Silicon/Silicium/SiliciumPkg/Sec/AArch64/ModuleEntryPoint.S")
DEVICE_BUILD = Path("Platforms/Xiaomi/diziPkg/DeviceBuild.py")

MODULES = (
    "UniXNUPkg/Application/UniXNU/UniXNU.inf",
    "UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf",
    "DarwinBootPkg/Driver/DarwinBoot.inf",
)
MARKER = "DIZI_UNIXNU_ENTRY_ARG_HOB"
ENTRY_HOB_GUID = (
    "  { 0xDAEE82E6, 0x8090, 0x4E72, "
    "{ 0xBF, 0xB9, 0x78, 0xC1, 0x3C, 0xD4, 0xE3, 0x59 } };"
)


def once(source: str, needle: str, replacement: str, name: str) -> str:
    count = source.count(needle)
    if count != 1:
        raise RuntimeError(f"{name}: expected one {needle!r}, got {count}")
    return source.replace(needle, replacement, 1)


def prepare(
    mu: Path,
    unixnu_package: Path,
    darwinboot_package: Path,
    *,
    dry_run: bool = False,
) -> dict:
    """Fail before writing unless all inputs and exact edit anchors are valid."""
    mu, unixnu_package, darwinboot_package = (
        mu.resolve(), unixnu_package.resolve(), darwinboot_package.resolve()
    )
    for module in MODULES:
        root = unixnu_package if module.startswith("UniXNUPkg/") else darwinboot_package
        if not (root / module).is_file():
            raise FileNotFoundError(f"Required upstream INF missing: {root / module}")

    files = (DSC, FDF, SEC, SEC_ASM, DEVICE_BUILD)
    source = {}
    for rel in files:
        path = mu / rel
        source[rel] = path.read_text(encoding="utf-8")

    if any(MARKER in text for text in source.values()):
        raise RuntimeError("UniXNU handoff already patched; start from a clean checkout")
    if any(module in source[DSC] or f"INF {module}" in source[FDF] for module in MODULES):
        raise RuntimeError("UniXNU integration already exists or is partial")

    # Board DSC: library mappings + firmware components. BootSelector is
    # responsible for launching the FV app; do not register BootOrder.
    dsc = source[DSC]
    dsc = once(
        dsc, "[LibraryClasses]\n",
        "[LibraryClasses]\n"
        "  UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf\n"
        "  HobLib|MdePkg/Library/DxeHobLib/DxeHobLib.inf\n"
        "  FdtLib|MdePkg/Library/BaseFdtLib/BaseFdtLib.inf\n",
        "dizi DSC library section"
    )
    dsc = once(
        dsc, "[Components]\n",
        "[Components]\n" + "".join("  " + module + "\n" for module in MODULES),
        "dizi DSC component section"
    )

    # FvMain is compressed into FVMAIN_COMPACT. Embed UniXNU and both
    # supporting drivers, but NOT UniXNUDxe: it writes Boot#### to NVRAM.
    fdf = once(
        source[FDF], "  !include QcomPkg/Extra.fdf.inc",
        "".join("  INF " + module + "\n" for module in MODULES)
        + "\n  !include QcomPkg/Extra.fdf.inc",
        "dizi FDF FvMain"
    )

    # BootShim keeps the ABL/FDT pointer in x0. The original Mu SEC overwrites
    # x0 before DXE, preventing UniXNURamDiskDxe from finding the FAT initrd.
    # Preserve it in writable FV memory before the first BL, then publish a HOB.
    asm = once(
        source[SEC_ASM], "ASM_FUNC (_ModuleEntryPoint)\n",
        "ASM_FUNC (_ModuleEntryPoint)\n"
        "  // " + MARKER + ": preserve ABL x0 before any BL clobbers it.\n"
        "  adr   x1, ASM_PFX (gDiziUnixnuEntryArg0)\n"
        "  str   x0, [x1]\n",
        "SEC AArch64 entry"
    )
    asm += (
        "\n  // " + MARKER + ": RAM-backed slot, one 64-bit FDT pointer.\n"
        "  .align 3\n"
        "  .global ASM_PFX (gDiziUnixnuEntryArg0)\n"
        "ASM_PFX (gDiziUnixnuEntryArg0):\n"
        "  .quad 0\n"
    )

    sec = once(
        source[SEC], '#include "Sec.h"\n',
        '#include "Sec.h"\n\n'
        '// ' + MARKER + ': FDT x0 -> GUID HOB for UniXNURamDiskDxe.\n'
        'extern UINT64 gDiziUnixnuEntryArg0;\n'
        'STATIC CONST EFI_GUID mDiziUnixnuEntryHobGuid =\n'
        + ENTRY_HOB_GUID + '\n',
        "SEC includes"
    )
    sec = once(
        sec, "  // Run Library Cconstructors\n",
        "  // " + MARKER + ": publish only the pointer, never touch flash.\n"
        "  {\n"
        "    UINT64 EntryArg = gDiziUnixnuEntryArg0;\n"
        "    BuildGuidDataHob (&mDiziUnixnuEntryHobGuid, &EntryArg, sizeof (EntryArg));\n"
        "  }\n\n"
        "  // Run Library Cconstructors\n",
        "SEC HOB insertion"
    )

    # edk2toolext's DeviceBuild.py supplies its own package paths; merely
    # exporting PACKAGES_PATH from the shell is not sufficient.
    package_paths = (
        Path(os.path.relpath(unixnu_package, mu)).as_posix(),
        Path(os.path.relpath(darwinboot_package, mu)).as_posix(),
    )
    for candidate in package_paths:
        if candidate.startswith("../"):
            raise ValueError("Clone UniXNU under the Mu workspace to keep builds isolated")
    device_build = once(
        source[DEVICE_BUILD], '        "Platforms/Xiaomi",\n',
        '        "Platforms/Xiaomi",\n'
        + "".join(f'        "{p}",\n' for p in package_paths),
        "dizi edk2toolext PackagesPath"
    )
    changes = {DSC: dsc, FDF: fdf, SEC: sec, SEC_ASM: asm,
               DEVICE_BUILD: device_build}
    report = {
        "board": "dizi",
        "dry_run": dry_run,
        "files": [str(path) for path in files],
        "firmware_modules": list(MODULES),
        "entry_arg_hob_guid": "DAEE82E6-8090-4E72-BFB9-78C13CD4E359",
        "requires_packages_path": list(package_paths),
        "requires_fat_initrd": True,
        "requires_abl_initrd_handoff": True,
        "android_partitions_modified": False,
        "boot_order_untouched": True,
        "xnu_boot_verified": False,
    }
    if not dry_run:
        for path, replacement in changes.items():
            (mu / path).write_text(replacement, encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu", type=Path, help="Fresh Mu-Silicium dizi source checkout")
    ap.add_argument("--unixnu-package", type=Path, required=True,
                    help="Path to UniXNU checkout's package/ directory")
    ap.add_argument("--darwinboot-package", type=Path, required=True,
                    help="Path to UniXNU checkout's drivers/DarwinBoot directory")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    report = prepare(args.mu, args.unixnu_package, args.darwinboot_package,
                     dry_run=args.dry_run)
    formatted = json.dumps(report, indent=2) + "\n"
    print(formatted, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(formatted, encoding="utf-8")


if __name__ == "__main__":
    main()

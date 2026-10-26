#!/usr/bin/env python3
"""Instrument the pinned UniXNURamDiskDxe without touching Android partitions.

Records precise DXE/FDT/initrd failure state in an ephemeral EFI protocol.
The status handle remains even if ABL supplied no usable device tree.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SRC = Path("External/UniXNU/package/UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.c")
GUID = "3ea6eac1-9556-4f49-a10b-fc87426d6348"
MARKER = "DIZI_RAM_DIAG_PROTOCOL_V1"


def once(s: str, old: str, new: str, name: str) -> str:
    n = s.count(old)
    if n != 1:
        raise ValueError(f"{name}: expected one source anchor, found {n}")
    return s.replace(old, new, 1)


def patch(mu: Path, dry_run: bool = False) -> dict:
    path = mu.resolve() / SRC
    code = path.read_text()
    if MARKER in code:
        raise ValueError("Ram diagnostic already integrated")
    code = once(code, "#define RAM_BLOCK_SIZE  512",
        """// DIZI_RAM_DIAG_PROTOCOL_V1 - volatile diagnostic protocol, not NVRAM.
STATIC CONST EFI_GUID mDiziRamDiagGuid = {
  0x3ea6eac1, 0x9556, 0x4f49,
  { 0xa1, 0x0b, 0xfc, 0x87, 0x42, 0x6d, 0x63, 0x48 }
};
typedef struct { UINT32 Stage; UINT32 Reserved; } DIZI_RAM_DIAG;
STATIC DIZI_RAM_DIAG mDiziRamDiag = { 1, 0 };
#define RAM_BLOCK_SIZE  512""", "status protocol declaration")
    code = once(code, '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no /chosen\\n"));',
        '    mDiziRamDiag.Stage = 5;\n    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no /chosen\\n"));',
        "FDT chosen state")
    code = once(code, '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no initrd in /chosen\\n"));',
        '    mDiziRamDiag.Stage = 6;\n    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no initrd in /chosen\\n"));',
        "initrd missing")
    code = once(code, '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd 0x%lx-0x%lx is not a whole number of sectors\\n", Start, End));',
        '    mDiziRamDiag.Stage = 7;\n    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd 0x%lx-0x%lx is not a whole number of sectors\\n", Start, End));',
        "initrd alignment")
    code = once(code,
        '  DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd block device 0x%lx size 0x%lx %r\\n", Start, End - Start, Status));',
        '  mDiziRamDiag.Stage = EFI_ERROR (Status) ? 8 : 9;\n'
        '  DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd block device 0x%lx size 0x%lx %r\\n", Start, End - Start, Status));',
        "BlockIo publication status")
    code = once(code,
        '  Hob = GetFirstGuidHob (&mEntryArgHobGuid);',
        """  // Publish diagnostic state before any early returns. No persistent
  // EFI variable, block write, boot option or memory scan is involved.
  EFI_STATUS DiagStatus = gBS->InstallProtocolInterface (
                               &ImageHandle, (EFI_GUID *)&mDiziRamDiagGuid,
                               EFI_NATIVE_INTERFACE, &mDiziRamDiag
                               );
  if (EFI_ERROR (DiagStatus)) {
    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: diagnostic protocol %r\\n", DiagStatus));
  }
  Hob = GetFirstGuidHob (&mEntryArgHobGuid);""",
        "publish diagnostic status at DXE entry")
    code = once(code,
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no entry argument HOB\\n"));',
        '    mDiziRamDiag.Stage = 2;\n    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no entry argument HOB\\n"));',
        "missing entry HOB")
    code = once(code,
        '  if (GET_GUID_HOB_DATA_SIZE (Hob) < sizeof (UINT64)) {\n    return EFI_COMPROMISED_DATA;',
        '  if (GET_GUID_HOB_DATA_SIZE (Hob) < sizeof (UINT64)) {\n    mDiziRamDiag.Stage = 3;\n    return EFI_COMPROMISED_DATA;',
        "malformed entry HOB")
    code = once(code,
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: x0 0x%lx is not a device tree\\n", Dtb));',
        '    mDiziRamDiag.Stage = 4;\n    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: x0 0x%lx is not a device tree\\n", Dtb));',
        "invalid FDT")
    code = once(code, '  PublishInitrd ((VOID *)(UINTN)Dtb);',
        '  mDiziRamDiag.Stage = 10;  // FDT present, examining initrd props.\n'
        '  PublishInitrd ((VOID *)(UINTN)Dtb);',
        "FDT recognized")
    report = {
        "driver": str(SRC),
        "guid": GUID,
        "stages": {
            "1": "driver started",
            "2": "no entry HOB",
            "3": "malformed HOB",
            "4": "invalid FDT",
            "5": "FDT chosen missing",
            "6": "FDT initrd props missing",
            "7": "invalid DTB initrd address or unsafe size",
            "8": "BlockIo publication failed",
            "9": "BlockIo published",
            "10": "FDT recognized",
            "11": "not a raw FAT32 at FDT initrd start",
            "12": "invalid FAT32 BPB",
            "13": "FAT32 size exceeds FDT memory range"
        },
        "android_partitions_written": False,
        "nvram_written": False,
        "hardware_verified": False,
        "dry_run": dry_run
    }
    if not dry_run:
        path.write_text(code)
    return report


def main() -> None:
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("mu", type=Path)
    arg.add_argument("--dry-run", action="store_true")
    arg.add_argument("--report", type=Path)
    a = arg.parse_args()
    report = patch(a.mu, a.dry_run)
    print(json.dumps(report, indent=2))
    if a.report:
        a.report.parent.mkdir(parents=True, exist_ok=True)
        a.report.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

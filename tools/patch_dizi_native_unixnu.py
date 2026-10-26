#!/usr/bin/env python3
"""Make the upstream UniXNU UI the *primary* dizi BDS menu.

Applied only inside an isolated pinned Mu-Silicium checkout AFTER both
the board selector and UniXNU firmware overlays. This leaves the original
PMIC/SPMI R3 sources and compiled recovery selector intact in FV, but BDS
starts UniXNU.efi (by its upstream FILE_GUID) instead of DiziBootSelector.

UniXNU must be launched with the upstream "unixnu:firmware" LoadOptions
marker so it connects block controllers before looking for unixnu.toml.
No BootOrder/NVRAM modification, storage write or MMIO write here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BDS = Path("Platforms/Xiaomi/diziPkg/Library/DiziDeviceBootManagerLib/DiziBootManager.c")
INF = Path("Platforms/Xiaomi/diziPkg/Library/DiziDeviceBootManagerLib/DiziDeviceBootManagerLib.inf")
HEADER = "#include <Protocol/LoadedImage.h>\n"
OLD_GUID = "0x8b56dab9, 0xa18d, 0x40a4, { 0x97, 0xec, 0xdf, 0xcc, 0x72, 0xee, 0x1f, 0x66 }"
UNIXNU_GUID = "0x9b665204, 0xa133, 0x47a2, { 0x93, 0x96, 0x9e, 0x2b, 0x37, 0x0a, 0x4e, 0x25 }"
MARKER = "DIZI_UNIXNU_PRIMARY_FIRMWARE_MENU"


def once(text: str, old: str, new: str, what: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{what}: expected one anchor {old!r}, found {count}")
    return text.replace(old, new, 1)


def patch(root: Path, *, dry_run: bool = False) -> dict:
    root = root.resolve()
    bds_file, inf_file = root / BDS, root / INF
    bds, inf = bds_file.read_text(), inf_file.read_text()
    if MARKER in bds:
        raise ValueError("Primary UniXNU already patched")
    if OLD_GUID not in bds:
        raise ValueError("Original selector firmware GUID missing (wrong base?)")
    if "DiziLaunchEmbeddedSelector ();" not in bds:
        raise ValueError("PMIC R3 selector BDS hook absent")
    bds = once(bds, OLD_GUID, UNIXNU_GUID, "FV GUID switch")
    bds = once(bds, "#include <Protocol/FirmwareVolume2.h>",
               HEADER + "#include <Protocol/FirmwareVolume2.h>", "loaded-image protocol include")
    bds = once(
        bds, "STATIC EFI_GUID mDiziSelectorFfsGuid =",
        "/* " + MARKER + ": stock UniXNU EFI_APPLICATION, not the R3 selector. */\n"
        "STATIC CONST CHAR16 mDiziUniXnuFirmwareMarker[] = L\"unixnu:firmware\";\n"
        "STATIC EFI_GUID mDiziSelectorFfsGuid =",
        "firmware marker"
    )
    anchor = "    Status = gBS->StartImage (LoadedImage, NULL, NULL);"
    addition = """    {
      EFI_LOADED_IMAGE_PROTOCOL *Loaded = NULL;
      EFI_STATUS ImageStatus = gBS->HandleProtocol (
                                  LoadedImage,
                                  &gEfiLoadedImageProtocolGuid,
                                  (VOID **)&Loaded
                                  );
      if (EFI_ERROR (ImageStatus) || Loaded == NULL) {
        DEBUG ((DEBUG_ERROR, "[dizi unixnu] LoadedImage unavailable: %r\\n", ImageStatus));
        (VOID)gBS->UnloadImage (LoadedImage);
        break;
      }
      // Upstream UniXNU.c recognizes this marker as a firmware boot
      // option, connects actual EFI controllers, and scans FAT volumes.
      Loaded->LoadOptions = (VOID *)mDiziUniXnuFirmwareMarker;
      Loaded->LoadOptionsSize = sizeof (mDiziUniXnuFirmwareMarker);
    }

""" + anchor
    bds = once(bds, anchor, addition, "UniXNU firmware image launch")
    bds = once(bds, "  DiziLaunchEmbeddedSelector ();",
               "  // UniXNU is the PRIMARY GUI. R3 selector stays embedded as recovery.\n"
               "  DiziLaunchEmbeddedSelector ();", "menu launch")
    inf = once(inf, "  gEfiFirmwareVolume2ProtocolGuid",
               "  gEfiLoadedImageProtocolGuid\n  gEfiFirmwareVolume2ProtocolGuid",
               "loaded-image INF protocol")
    report = {
        "base": "dizi PMIC/SPMI R3",
        "primary_menu": "upstream UniXNU (real app, firmware-mode)",
        "preserved": "PMIC/SPMI files, R3 selector FFS, USB init, BDS button registration",
        "firmware_marker": "unixnu:firmware",
        "boot_order_modified": False,
        "storage_modified": False,
        "xnu_hardware_verified": False,
        "dry_run": dry_run,
    }
    if not dry_run:
        bds_file.write_text(bds)
        inf_file.write_text(inf)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mu", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path)
    opts = parser.parse_args()
    report = patch(opts.mu, dry_run=opts.dry_run)
    print(json.dumps(report, indent=2))
    if opts.report:
        opts.report.parent.mkdir(parents=True, exist_ok=True)
        opts.report.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

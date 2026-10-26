#!/usr/bin/env python3
"""Apply the native dizi EDK2 boot-selector overlay to KSN2redawew/Mu-Silicium.

Does not flash devices or load Android /data. Fails closed on upstream changes.
The actual Android and XNU firmware-file loaders do not yet exist.
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
from pathlib import Path

DSC = Path("Platforms/Xiaomi/diziPkg/dizi.dsc")
FDF = Path("Platforms/Xiaomi/diziPkg/dizi.fdf")
BDS = Path("Silicon/Qualcomm/QcomPkg/Library/PlatformBootManagerLib/PlatformBootManager.c")
BDS_INF = Path("Silicon/Qualcomm/QcomPkg/Library/PlatformBootManagerLib/PlatformBootManagerLib.inf")
DIZI_BDS = Path("Platforms/Xiaomi/diziPkg/Library/DiziDeviceBootManagerLib/DiziBootManager.c")
DIZI_BDS_INF = Path("Platforms/Xiaomi/diziPkg/Library/DiziDeviceBootManagerLib/DiziDeviceBootManagerLib.inf")
INF = "DiziBootPkg/BootSelector/BootSelector.inf"
PARENT = Path(__file__).resolve().parents[1]
MARKER = "DiziLaunchEmbeddedSelector"

def replace_once(s: str, old: str, new: str, context: str) -> str:
    occurrences = s.count(old)
    if occurrences != 1:
        raise RuntimeError(f"{context}: unexpected upstream layout; expected 1 occurrence of {old!r}, got {occurrences}")
    return s.replace(old, new, 1)

def write_changed(p: Path, original: str, new: str) -> bool:
    if original == new:
        return False
    p.write_bytes(new.encode("utf-8"))
    return True

def add_selector(workspace: Path, dry_run: bool = False) -> dict:
    """Patch board DSC/FDF and active Qcom DeviceBootManager BDS library."""
    # Prefer this fork's DIZI-only BDS library, preserving the fixed
    # Power/Volume ConIn registration. The old shared QCOM BDS remains
    # supported for reproducing historical overlays on pinned upstream.
    has_dizi_bds = (workspace / DIZI_BDS).is_file() and (workspace / DIZI_BDS_INF).is_file()
    selected_bds = DIZI_BDS if has_dizi_bds else BDS
    selected_inf = DIZI_BDS_INF if has_dizi_bds else BDS_INF
    paths = [workspace / p for p in (DSC,FDF,selected_bds,selected_inf)]
    for p in paths:
        if not p.is_file():
            raise FileNotFoundError(f"Missing board source {p}")

    fragment = (PARENT / "tools/ksn_dizi_selector_launch.c.inc").read_text()
    selector = PARENT / "DiziBootPkg/BootSelector"
    for fn in ("BootSelector.c", "BootSelector.inf", "DiziScaledUi.c", "DiziScaledUi.h", "DiziPmicKeys.c", "DiziPmicKeys.h", "DiziSpmiArbProbe.c", "DiziSpmiArbProbe.h", "DiziSpmiArbRead.c"):
        if not (selector / fn).is_file():
            raise FileNotFoundError(f"Missing selector source {fn}")
    # Only apply a complete deterministic patch when source matches known markers.
    ds = paths[0].read_text()
    ff = paths[1].read_text()
    bs = paths[2].read_text()
    bi = paths[3].read_text()
    if INF in ds or INF in ff or MARKER in bs:
        raise RuntimeError("selector already integrated or partial overlay found; use fresh source checkout")

    ds2 = replace_once(ds,
        "[Components]\n", "[Components]\n  " + INF + "\n",
        "DSC components")
    ff2 = replace_once(ff, "  !include QcomPkg/Extra.fdf.inc",
        "  INF " + INF + "\n\n  !include QcomPkg/Extra.fdf.inc",
        "FDF compressed FV")
    bs2 = replace_once(bs, "#include <Library/RfsProtectionLib.h>",
        "#include <Library/RfsProtectionLib.h>\n"
        "#include <Protocol/FirmwareVolume2.h>\n"
        "#include <Protocol/Usb2HostController.h>\n"
        "#include <Protocol/PciRootBridgeIo.h>\n"
        "#include <Protocol/PciIo.h>\n"
        "#include <Pi/PiFirmwareFile.h>",
        "Qcom BDS includes")
    bs2 = replace_once(bs2, "STATIC\nVOID\nDummyNotify", fragment + "\nSTATIC\nVOID\nDummyNotify", "BDS fragment placement")
    # This is after console + SD event; the platform keypad protocol and GOP
    # have been connected by the parent BootManager implementation.
    start=bs2.index("DeviceBootManagerAfterConsole ()")
    end=bs2.index("DeviceBootManagerOnDemandConInConnect ()", start)
    section=bs2[start:end]
    section2=replace_once(section, "  gBS->CloseEvent  (InitEvent);\n\n  return NULL;",
         "  gBS->CloseEvent  (InitEvent);\n\n"
         "  // Launch the AARCH64 EFI application embedded in FVMAIN.\n"
         "  // Missing XNU / Android EFI loaders safely return to firmware.\n"
         "  // USB controller init normally runs after the on-demand BDS callback.\n"
         "  // Initialize it before the selector to allow OTG keyboard input.\n"
         "  DiziInitUsbHostEarly ();\n"
         "  DiziLaunchEmbeddedSelector ();\n\n  return NULL;",
         "AfterConsole hook")
    bs2=bs2[:start]+section2+bs2[end:]
    if "[Protocols]" in bi:
        bi2 = replace_once(bi, "[Protocols]",
            "[Protocols]\n  gEfiFirmwareVolume2ProtocolGuid\n  gEfiUsb2HcProtocolGuid\n  gEfiPciRootBridgeIoProtocolGuid\n  gEfiPciIoProtocolGuid",
            "DIZI BDS INF protocol declarations")
    else:
        bi2 = replace_once(bi, "[Guids]",
            "[Protocols]\n  gEfiFirmwareVolume2ProtocolGuid\n  gEfiUsb2HcProtocolGuid\n  gEfiPciRootBridgeIoProtocolGuid\n  gEfiPciIoProtocolGuid\n\n[Guids]",
            "shared BDS INF protocol declarations")

    results = {str(p.relative_to(workspace)):len(value) for p,value in zip(paths,(ds2,ff2,bs2,bi2))}
    if dry_run:
        return {"dry_run": True,"patched":results}

    for p,orig,val in zip(paths,(ds,ff,bs,bi),(ds2,ff2,bs2,bi2)):
        write_changed(p,orig,val)
    out = workspace / "Platforms/Xiaomi/DiziBootPkg/BootSelector"
    out.mkdir(parents=True,exist_ok=True)
    for fn in ("BootSelector.c", "BootSelector.inf", "DiziScaledUi.c", "DiziScaledUi.h", "DiziPmicKeys.c", "DiziPmicKeys.h", "DiziSpmiArbProbe.c", "DiziSpmiArbProbe.h", "DiziSpmiArbRead.c"):
        shutil.copy2(selector / fn, out / fn)
    return {"dry_run": False, "patched": results,
            "bds_library": str(selected_bds),
            "preserves_dizi_input_fix": has_dizi_bds,
            "copied_selector":str(out.relative_to(workspace)),
            "autostart_via_bds":True,
            "android_boot_supported":False, "xnu_boot_supported":False}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("upstream", type=Path, help="KSN2redawew/Mu-Silicium checkout")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path)
    args=ap.parse_args()
    result=add_selector(args.upstream.resolve(),args.dry_run)
    print(json.dumps(result,indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2)+"\n")

if __name__ == "__main__":
    main()

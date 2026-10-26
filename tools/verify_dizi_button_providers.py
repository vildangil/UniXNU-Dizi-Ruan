#!/usr/bin/env python3
"""Audit the DIZI UEFI FV for button drivers and optional PMIC isolation.

No device I/O. These checks inspect the packaged Android boot-v4 image and
its LZMA-compressed EFI FV. Runtime key delivery remains unverified.
"""
import argparse
import json
import lzma
from pathlib import Path
import struct
import uuid
import zlib
from verify_ksn_dizi_fv import scan_ffs, LZMA_GUID, verify

BUTTONS = uuid.UUID("5BD181DB-0487-4F1A-AE73-820E165611B3")
SPMI = uuid.UUID("2A7B4BEF-80CD-49E1-B473-374BA4D673FC")
PMIC = uuid.UUID("5776232E-082D-4B75-9A0E-FE1D13F7A5D9")


def check(blob, *, expect_pmic_absent=False):
    base = verify(blob)  # Board identity, boot v4, DTB, EFI menu and PE machine.
    size = struct.unpack_from("<I", blob, 8)[0]
    z = zlib.decompressobj(31)
    firmware = z.decompress(blob[4096:4096 + size]) + z.flush()
    inner_volumes = []
    for _guid, ftype, data, _position, _length in scan_ffs(firmware[0x70:]):
        if ftype != 0x0b:
            continue
        if len(data) < 24 or data[3] != 0x02 or uuid.UUID(bytes_le=data[4:20]) != LZMA_GUID:
            continue
        section_size = int.from_bytes(data[:3], "little")
        offset = int.from_bytes(data[20:22], "little")
        if not 24 <= offset < section_size <= len(data):
            raise ValueError("unexpected guided FV section")
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        expanded = decoder.decompress(data[offset:section_size])
        if not decoder.eof:
            raise ValueError("truncated FV LZMA stream")
        idx = expanded.find(b"_FVH")
        if idx < 40:
            raise ValueError("inner FV header missing")
        inner_volumes.append(expanded[idx - 40:])
    if len(inner_volumes) != 1:
        raise ValueError("expected exactly one inner FV")
    present = {str(guid): {"bytes": size, "type": kind} for guid, kind, _data, _pos, size in scan_ffs(inner_volumes[0])}
    required = {"ButtonsDxe": BUTTONS, "SPMIDxe": SPMI, "PmicDxe": PMIC}
    presence = {name: str(guid) in present for name, guid in required.items()}
    if not presence["ButtonsDxe"]:
        raise ValueError("ButtonsDxe missing from firmware")
    if expect_pmic_absent:
        if presence["SPMIDxe"] or presence["PmicDxe"]:
            raise ValueError("Black-screen isolation failed: SPMI/PmicDxe still in firmware")
    else:
        missing = [name for name, installed in presence.items() if not installed]
        if missing:
            raise ValueError("Missing PMIC button provider FFS: " + ", ".join(missing))
    return {
        "status": ("PMIC_CORE_EXCLUDED_FOR_SCREEN_RECOVERY_UNTESTED"
                    if expect_pmic_absent else "FIRMWARE_PROVIDER_FFS_PRESENT_NOT_HARDWARE_VERIFIED"),
        "menu_ffs": base["selector"],
        "pmic_driver_presence": presence,
        "driver_ffs": {name: present[str(guid)] for name, guid in required.items()
                       if presence[name]},
        "power_button_verified": False,
        "volume_up_verified": False,
        "volume_down_verified": False,
        "never_flash": True,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("image", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--expect-pmic-absent", action="store_true",
                   help="Fail unless SPMIDxe and PmicDxe are both absent (screen recovery)")
    args = p.parse_args()
    report = check(args.image.read_bytes(), expect_pmic_absent=args.expect_pmic_absent)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if args.report:
        args.report.write_text(text)


if __name__ == "__main__":
    main()

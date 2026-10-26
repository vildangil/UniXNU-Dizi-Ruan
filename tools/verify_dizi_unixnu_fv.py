#!/usr/bin/env python3
"""Verify UniXNU EFI and its DXE support are IN the built DIZI firmware FV.

Host-only format audit; does not assert that XNU ran or devices work.
"""
from __future__ import annotations

import argparse
import json
import lzma
import struct
import uuid
import zlib
from pathlib import Path

from verify_ksn_dizi_fv import scan_ffs, check, verify as verify_menu

MODULES = {
    uuid.UUID("9b665204-a133-47a2-9396-9e2b370a4e25"): ("UniXNU.efi", 0x09),
    uuid.UUID("75ca63ad-fbae-4a06-92a0-f937c671251d"): ("UniXNURamDiskDxe", 0x07),
    uuid.UUID("1b64af87-8415-4b57-9b16-680d70913b9f"): ("DarwinBoot", 0x07),
}
LZMA_GUID = uuid.UUID("ee4e5898-3914-4259-9d6e-dc7bd79403cf")


def inner_fv(blob: bytes) -> bytes:
    check(blob.startswith(b"ANDROID!"), "not Android boot image")
    size = struct.unpack_from("<I", blob, 8)[0]
    gz = zlib.decompressobj(31)
    image = gz.decompress(blob[4096:4096+size]) + gz.flush()
    check(gz.eof, "invalid gzip firmware")
    check(image[0x70+40:0x70+44] == b"_FVH", "no outer FV")
    for _guid, ftype, contents, _pos, _length in scan_ffs(image[0x70:]):
        if ftype != 0x0b:
            continue
        check(uuid.UUID(bytes_le=contents[4:20]) == LZMA_GUID, "unexpected compression GUID")
        n = int.from_bytes(contents[:3], "little")
        offset = struct.unpack_from("<H", contents, 20)[0]
        check(24 <= offset < n <= len(contents), "bad LZMA section")
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        body = dec.decompress(contents[offset:n])
        check(dec.eof, "incomplete LZMA stream")
        index = body.find(b"_FVH")
        check(index >= 40, "inner _FVH absent")
        return body[index-40:]
    raise ValueError("no nested firmware volume")


def has_arm64_pe(data: bytes) -> bool:
    offset = 0
    while offset + 4 <= len(data):
        size = int.from_bytes(data[offset:offset+3], "little")
        if size < 4 or offset + size > len(data):
            raise ValueError("malformed FFS section")
        if data[offset+3] == 0x10:
            pe = data[offset+4:offset+size]
            if len(pe) >= 0x40 and pe[:2] == b"MZ":
                dos_off = struct.unpack_from("<I", pe, 0x3c)[0]
                if dos_off + 6 <= len(pe) and pe[dos_off:dos_off+4] == b"PE\x00\x00":
                    if struct.unpack_from("<H", pe, dos_off+4)[0] == 0xaa64:
                        return True
        offset = (offset + size + 3) & ~3
    return False


def verify(blob: bytes) -> dict:
    verify_menu(blob)
    fv = inner_fv(blob)
    found: dict[str, dict] = {}
    for guid, ftype, data, offset, length in scan_ffs(fv):
        if guid not in MODULES:
            continue
        name, required_type = MODULES[guid]
        check(name not in found, f"duplicate {name} FFS")
        check(ftype == required_type, f"incorrect FFS filetype for {name}")
        check(has_arm64_pe(data), f"{name} lacks PE32+ AArch64 image")
        found[name] = {"offset": offset, "bytes": length, "file_guid": str(guid)}
    check(len(found) == len(MODULES),
          f"UniXNU components missing: {set(n for n, _ in MODULES.values()) - set(found)}")
    return {"board": "dizi", "modules": found, "verified_fv": True,
            "xnu_kernel_executed": False, "android_dualboot_verified": False}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("boot_img", type=Path)
    p.add_argument("--report", type=Path)
    opts = p.parse_args()
    result = verify(opts.boot_img.read_bytes())
    print(json.dumps(result, indent=2))
    if opts.report:
        opts.report.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()

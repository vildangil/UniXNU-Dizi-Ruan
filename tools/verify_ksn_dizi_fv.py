#!/usr/bin/env python3
"""Verify selector FFS is actually compiled into KSN dizi's LZMA-compressed FV.

This does not prove hardware bootability or Android/XNU loading.
"""
import argparse
import hashlib
import json
import lzma
import struct
import uuid
import zlib
from pathlib import Path

MENU_GUID = uuid.UUID("8b56dab9-a18d-40a4-97ec-dfcc72ee1f66")
LZMA_GUID = uuid.UUID("ee4e5898-3914-4259-9d6e-dc7bd79403cf")

def check(condition, why):
    if not condition:
        raise ValueError(why)

def scan_ffs(fv: bytes):
    """Walk ordinary 8-aligned FFS files in one firmware volume."""
    check(len(fv) >= 72 and fv[40:44] == b"_FVH", "no EFI firmware-volume header")
    length = struct.unpack_from("<Q", fv, 32)[0]
    header = struct.unpack_from("<H", fv, 48)[0]
    check(72 <= header <= length <= len(fv), "invalid FV geometry")
    pos = (header + 7) & ~7
    while pos + 24 <= length:
        if fv[pos:pos+24] == b"\xff"*24:
            pos += 8
            continue
        data = fv[pos:pos+24]
        n = int.from_bytes(data[20:23], "little")
        check(24 <= n < 0xffffff and pos+n <= length, f"invalid FFS at {pos:#x}")
        yield (uuid.UUID(bytes_le=data[:16]), data[18], fv[pos+24:pos+n], pos, n)
        pos = (pos+n+7) & ~7

def verify(blob: bytes, required_selector_string: str | None = None):
    check(blob[:8] == b"ANDROID!", "not an Android boot image")
    size, ramdisk, _os, hlen = struct.unpack_from("<4I", blob, 8)
    check((hlen, struct.unpack_from("<I", blob, 40)[0]) == (1584,4),
          "not Android boot v4")
    gz=zlib.decompressobj(31)
    firmware=gz.decompress(blob[4096:4096+size])+gz.flush()
    dtb=gz.unused_data
    check(gz.eof and len(dtb)>100 and dtb[:4]==b"\xd0\x0d\xfe\xed",
          "gzip/FDT invalid")
    check(b"Redmi Pad Pro" in dtb, "not DIZI FDT")
    check(firmware[0x70+40:0x70+44]==b"_FVH", "outer FV invalid")

    guided_sections=[]
    for _guid, ftype, data, pos, length in scan_ffs(firmware[0x70:]):
        # The compact FV uses a GUID-defined LZMA section.
        if ftype != 0x0b:
            continue
        check(len(data)>24 and data[3]==0x02, "FV image not GUID-defined")
        check(uuid.UUID(bytes_le=data[4:20]) == LZMA_GUID,
              "unsupported compressed FV GUID")
        section_size=int.from_bytes(data[:3],"little")
        data_offset=int.from_bytes(data[20:22],"little")
        check(24 <= data_offset < section_size <= len(data),
              "invalid LZMA GUID-defined section bounds")
        decoder=lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        inner=decoder.decompress(data[data_offset:section_size])
        check(decoder.eof, "LZMA stream truncated")
        guided_sections.append(inner)

    check(len(guided_sections)==1, "unexpected compact firmware structure")
    inner=guided_sections[0]
    idx=inner.find(b"_FVH")
    check(idx>=40, "no inner FV header")
    inner=inner[idx-40:]
    found=[]
    for guid, ftype, data, pos, length in scan_ffs(inner):
        if guid!=MENU_GUID:
            continue
        check(ftype==0x09, "menu FFS is not an EFI application")
        # Inspect nested section headers to find a PE32 image.
        q=0
        matched=False
        while q+4 <= len(data):
            n=int.from_bytes(data[q:q+3], "little")
            typ=data[q+3]
            check(n>=4 and q+n<=len(data), "malformed application section")
            pe=data[q+4:q+n]
            if typ==0x10:
                check(pe[:2]==b"MZ", "missing PE signature")
                off=struct.unpack_from("<I",pe,0x3c)[0]
                check(off+26 < len(pe) and pe[off:off+4]==b"PE\x00\x00",
                      "invalid ARM64 PE")
                machine=struct.unpack_from("<H",pe,off+4)[0]
                check(machine==0xaa64, "not an AARCH64 EFI binary")
                if required_selector_string is not None:
                    marker = required_selector_string.encode("ascii")
                    check(marker in pe,
                          "compiled selector PE32 is missing required build tag "
                          + repr(required_selector_string))
                matched=True
            q=(q+n+3)&~3
        check(matched, "selector has no PE32 image section")
        found.append({"ffs_offset":pos,"ffs_bytes":length,"pe_machine":"AARCH64"})
    check(len(found)==1, f"expected exactly one selector FFS, got {len(found)}")
    return {"boot_sha256":hashlib.sha256(blob).hexdigest(),
            "device":"dizi","android_boot_version":4,
            "firmware_bytes":len(firmware),"dtb_bytes":len(dtb),
            "selector":found[0],"selector_in_inner_fv":True,
            "verified_on_hardware":False,"android_xnu_chainload":False,
            "required_selector_string":required_selector_string}

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument("boot_img",type=Path)
    a.add_argument("--report",type=Path)
    a.add_argument("--require-selector-string",
                   help="ASCII marker that must be present inside compiled selector PE32")
    args=a.parse_args()
    result=verify(args.boot_img.read_bytes(), args.require_selector_string)
    print(json.dumps(result,indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(result,indent=2)+"\n")

if __name__=="__main__":
    main()

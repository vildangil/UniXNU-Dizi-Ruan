#!/usr/bin/env python3
"""Symbolize a Dizi EBS UEFI exception with a *measured* runtime EBS pointer.

Usage:
  python3 ci/symbolize_dizi_ebs.py --map DxeCore.map --efi DxeCore.efi \
      --ebs-pointer 0xFC369E3C --pc 0xFC369EAC

The pointer above is measured from the 2026-10-28 EBS pointer test photo.
New boots can use a different runtime value; read all sixteen digits. A raw exception PC cannot
be treated as an RVA; load-base relocation changes between boots.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import struct

SYM = re.compile(r"^([0-9a-fA-F]{8,16})\s+00000000\s+0\s+([A-Za-z_$?.][\w$@?.]*)\s*$")

def symbols_from_map(path: Path):
    result = []
    for line in path.read_text(errors="replace").splitlines():
        found = SYM.match(line.strip())
        if found:
            result.append((int(found.group(1), 16), found.group(2)))
    if not result:
        raise ValueError("No symbols found in LLD /lldmap output")
    return sorted(set(result))

def size_of_image(path: Path):
    b = path.read_bytes()
    if len(b) < 0x100 or b[:2] != b"MZ":
        raise ValueError("Not a PE image")
    peoff = struct.unpack_from("<I", b, 0x3c)[0]
    if b[peoff:peoff+4] != b"PE\0\0":
        raise ValueError("Bad PE signature")
    magic = struct.unpack_from("<H", b, peoff+24)[0]
    if magic not in (0x10b, 0x20b):
        raise ValueError("Unknown PE optional header")
    return struct.unpack_from("<I", b, peoff+24+56)[0]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--efi", type=Path, required=True)
    ap.add_argument("--ebs-pointer", type=lambda s: int(s, 0), required=True)
    ap.add_argument("--pc", type=lambda s: int(s, 0), required=True, action="append")
    args = ap.parse_args()
    symbols = symbols_from_map(args.map)
    ebss = set(rva for rva, name in symbols if name == "CoreExitBootServices")
    if len(ebss) != 1:
        raise SystemExit("Expected exactly one CoreExitBootServices RVA in this map")
    ebs_rva = ebss.pop()
    base = args.ebs_pointer - ebs_rva
    img_size = size_of_image(args.efi)
    if base < 0:
        raise SystemExit("EBS pointer is below mapped CoreExitBootServices RVA")
    # DXE Core may execute XIP or through FV/TE offsets. A non-page-aligned
    # inferred base is NOT proof of a wrong image; do not reject the photo.
    # A map-aligned RVA match alone also does NOT prove the runtime image.
    aligned = (base & 0xfff) == 0
    output = {
        "runtime_ebs_pointer": hex(args.ebs_pointer),
        "ebs_rva": hex(ebs_rva),
        "derived_dxecore_runtime_base": hex(base),
        "image_base_page_aligned": aligned,
        "image_base_confirmed": False,
        "alignment_note": (
            "4K-aligned candidate; still verify loaded module identity"
            if aligned else
            "Unaligned derived image base: could be FV/XIP/TE layout, a "
            "different loaded copy, or a thunk. Mapping below is only a "
            "hypothesis until actual runtime code bytes are checked."
        ),
        "pe_size_of_image": hex(img_size),
        "pc_results": [],
    }
    for pc in args.pc:
        rva = pc - base
        inside = 0 <= rva < img_size
        item = {"pc": hex(pc), "inside_dxecore_image": inside,
                "rva": hex(rva) if inside else None,
                "delta_from_ebs_entry": (
                    "+" if pc >= args.ebs_pointer else "-"
                ) + hex(abs(pc - args.ebs_pointer))}
        if inside:
            preceding = [s for s in symbols if s[0] <= rva]
            following = [s for s in symbols if s[0] > rva]
            if preceding:
                start, name = preceding[-1]
                item["nearest_preceding_symbol"] = name
                item["offset_from_symbol"] = hex(rva - start)
            if following:
                item["next_symbol_rva"] = hex(following[0][0])
            item["note"] = ("Nearest symbol only, not a source-line proof. "
                            "Confirm with DxeCore.disassembly.txt.")
        else:
            item["note"] = ("PC outside this DxeCore image: inspect other "
                            "loaded EFI modules and callback stack.")
        output["pc_results"].append(item)
    print(json.dumps(output, indent=2))

if __name__ == "__main__":
    main()

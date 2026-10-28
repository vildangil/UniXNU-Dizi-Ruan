#!/usr/bin/env python3
"""Capture the exact BdsDxe EFI image and verify old Windows KEP EBS hook is absent.

The hardware four-word fingerprint (NO-XNU #40639206923) was:
A9BD53F3 F9000BF5 A901FBFD B900012A at offsets 0,4,8,0x70.
These exact values appeared at BdsDxe section RVA 0x3E3C/0x3EAC inside
the LZMA-decompressed FVMAIN. They correspond to
KepExitBootServicesHook() -> PatchTransferToKernel().
No source or production UEFI image is modified here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path

FIRST_3=bytes.fromhex("f353bda9f50b00f9fdfb01a9")
STORE=0xB900012A

def find_hook(data: bytes) -> list[int]:
    hits=[]
    pos=0
    while True:
        pos=data.find(FIRST_3,pos)
        if pos<0:
            break
        if pos+0x74<=len(data) and struct.unpack_from("<I",data,pos+0x70)[0]==STORE:
            hits.append(pos)
        pos+=1
    return hits

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("dist",type=Path)
    args=ap.parse_args()
    mu=args.mu.resolve()
    root=mu/"Build/diziPkg/RELEASE_CLANGPDB/AARCH64"
    matches=list(root.glob("**/BdsDxe/OUTPUT/BdsDxe.efi"))
    if len(matches)!=1:
        raise SystemExit(f"Expected one freshly built BdsDxe.efi, found {matches}")
    src=matches[0]
    data=src.read_bytes()
    if not data.startswith(b"MZ") or len(data)<4096:
        raise SystemExit("Invalid built BdsDxe PE")
    # This is the precise four-instruction window that faulted on dizi.
    hits=find_hook(data)
    dest=args.dist.resolve()/"bds-kep"
    dest.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(src,dest/"BdsDxe.efi")
    m=src.parent.parent/"DEBUG/BdsDxe.map"
    if m.is_file():
        shutil.copyfile(m,dest/"BdsDxe.map")
    report={
        "source":"pinned Mu-Silicium KEP constructor disabled only in CI",
        "bds_efi_sha256":hashlib.sha256(data).hexdigest(),
        "bds_efi_size":len(data),
        "old_kep_four_word_fingerprint_offsets":[hex(x) for x in hits],
        "old_kep_four_word_fingerprint_absent":not hits,
        "original_ebs_expected":True,
        "original_ebs_runtime_verified":False,
        "xnu_entry_executed":False,
    }
    (args.dist.resolve()/"KEP-BYPASS-CHECK.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    if hits:
        raise SystemExit("Faulting KEP ExitBootServices hook is still linked into BdsDxe!")

if __name__=="__main__":
    main()

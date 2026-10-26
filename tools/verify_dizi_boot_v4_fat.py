#!/usr/bin/env python3
"""Read-only verification of FAT32 embedded in an Android boot-v4 image.

Checks boot header, byte-for-byte copied ramdisk, FAT32 boot sector,
directory chain and actual EFI/UniXNU/unixnu.toml without mounting
anything or writing to Android partitions.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct

PAGE=4096


def u16(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<H", blob, offset)[0]


def u32(blob: bytes, offset: int) -> int:
    return struct.unpack_from("<I", blob, offset)[0]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_dir(fat: bytes, first: int, data_at: int, sector_bytes: int) -> list[tuple[str,int,int]]:
    buf=fat[data_at + (first-2)*sector_bytes:data_at + (first-1)*sector_bytes]
    if len(buf)!=sector_bytes:
        raise ValueError("FAT directory outside volume")
    entries=[]
    long=[]
    for off in range(0,len(buf),32):
        ent=buf[off:off+32]
        if ent[0]==0: break
        if ent[0]==0xE5: long.clear(); continue
        if ent[11]==0x0F:
            chars=b"".join(ent[i:i+2] for i in (1,3,5,7,9,14,16,18,20,22,24,28,30))
            long.insert(0,chars)
            continue
        short=ent[:8].decode("ascii","replace").rstrip()
        ext=ent[8:11].decode("ascii","replace").rstrip()
        name=short + ("."+ext if ext else "")
        if long:
            raw=b"".join(long)
            text=raw.decode("utf-16le",errors="replace").split("\x00")[0].split("\uffff")[0]
            if text: name=text
        long=[]
        cluster=u16(ent,20)*65536+u16(ent,26)
        length=u32(ent,28)
        entries.append((name,cluster,length))
    return entries


def verify(boot_path: Path, fat_path: Path) -> dict:
    boot=boot_path.read_bytes()
    fat=fat_path.read_bytes()
    if boot[:8]!=b"ANDROID!": raise ValueError("invalid Android image")
    if u32(boot,40)!=4: raise ValueError("expected Android boot v4")
    kernel_bytes=u32(boot,8)
    ram_bytes=u32(boot,12)
    start=PAGE + (kernel_bytes + PAGE-1)//PAGE*PAGE
    if ram_bytes!=len(fat):
        raise ValueError(f"ramdisk header size mismatch: {ram_bytes} vs {len(fat)}")
    if boot[start:start+ram_bytes]!=fat:
        raise ValueError("Android boot image ramdisk does not match staged FAT")
    if fat[510:512]!=b"\x55\xaa" or fat[82:90]!=b"FAT32   ":
        raise ValueError("Android boot ramdisk lacks valid FAT32 sector")
    bps=u16(fat,11); spc=fat[13]
    reserved=u16(fat,14); fats=fat[16]; fat_sectors=u32(fat,36)
    if bps!=512 or spc==0 or reserved==0 or fats==0 or fat_sectors==0:
        raise ValueError("invalid FAT32 BPB")
    fat_data=(reserved+fats*fat_sectors)*bps
    cluster_bytes=bps*spc
    first_cluster=u32(fat,44)
    root=read_dir(fat,first_cluster,fat_data,cluster_bytes)
    def target(entries:list[tuple[str,int,int]],name:str)->tuple[int,int]:
        for n,c,size in entries:
            if n.casefold()==name.casefold():
                return c,size
        raise ValueError(f"missing FAT directory entry: {name}")
    efi,_=target(root,"EFI")
    un,_=target(read_dir(fat,efi,fat_data,cluster_bytes),"UniXNU")
    entries=read_dir(fat,un,fat_data,cluster_bytes)
    conf_cluster,conf_size=target(entries,"unixnu.toml")
    target(entries,"Payloads")
    config_pos=fat_data+(conf_cluster-2)*cluster_bytes
    cfg=fat[config_pos:config_pos+conf_size].decode("utf-8")
    if "version = 1" not in cfg or 'type = "xnu"' not in cfg:
        raise ValueError("FAT unixnu.toml missing schema or XNU entries")
    return {
        "boot_version": 4,
        "kernel_bytes": kernel_bytes,
        "ramdisk_offset": start,
        "ramdisk_bytes": ram_bytes,
        "staged_fat_sha256": sha(fat),
        "ramdisk_matches_boot_image": True,
        "fat32_sector_and_path_valid": True,
        "unixnu_configuration_bytes": conf_size,
        "xnu_entry_count": cfg.count('type = "xnu"'),
        "fat_found_in_uefi": False,
        "physical_xnu_tested": False
    }


def main() -> None:
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("boot_img",type=Path)
    cli.add_argument("fat_img",type=Path)
    cli.add_argument("--report",type=Path)
    args=cli.parse_args()
    report=verify(args.boot_img,args.fat_img)
    out=json.dumps(report,indent=2)+"\n"
    print(out,end="")
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(out)


if __name__=="__main__":
    main()

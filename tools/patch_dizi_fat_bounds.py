#!/usr/bin/env python3
"""Accept a complete FAT32 filesystem inside a non-sector-aligned Android initrd.

Runs after patch_dizi_ramdisk_diag.py against the pinned UniXNU source.
Never rounds an arbitrary pointer up, never scans unknown memory, and never
extends BlockIo beyond the FDT-reported initrd range. Stops safely when the
initrd is a compressed vendor blob or is shorter than the FAT volume.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

RAM = Path("External/UniXNU/package/UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.c")
TAG = "DIZI_FAT32_BOUNDED_INITRD_V1"

def once(src: str, old: str, new: str) -> str:
    count = src.count(old)
    if count != 1:
        raise ValueError(f"expected exactly one pinned driver anchor, found {count}: {old[:90]}")
    return src.replace(old, new, 1)

def patch(mu: Path, dry_run: bool = False) -> dict:
    path = mu.resolve() / RAM
    code = path.read_text()
    if TAG in code:
        raise ValueError("bounded FAT32 patch already applied")
    if "DIZI_RAM_DIAG_PROTOCOL_V1" not in code:
        raise ValueError("Apply patch_dizi_ramdisk_diag.py first")
    code = once(code, "  UINT64      End;\n", "  UINT64      End;\n  UINT64      Available;\n  UINT64      FatBytes;\n  UINT32      TotalSectors;\n  UINT8       *Boot;\n")
    old = '''  if ((End <= Start) || (((End - Start) % RAM_BLOCK_SIZE) != 0)) {
    mDiziRamDiag.Stage = 7;
    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd 0x%lx-0x%lx is not a whole number of sectors\\n", Start, End));
    return;
  }
'''
    new = '''  // DIZI_FAT32_BOUNDED_INITRD_V1: FDT end may include trailing vendor
  // bytes. FAT size comes from the boot-sector BPB, not from End - Start.
  // Do not expose any bytes after End, nor read an unvalidated range.
  if ((Start == 0) || (End <= Start)) {
    mDiziRamDiag.Stage = 7;
    return;
  }
  Available = End - Start;
  if ((Available < RAM_BLOCK_SIZE) || (Available > 512ULL * 1024 * 1024)) {
    mDiziRamDiag.Stage = 7;
    return;
  }
  Boot = (UINT8 *)(UINTN)Start;
  if ((Boot[510] != 0x55) || (Boot[511] != 0xAA) ||
      (CompareMem (Boot + 82, "FAT32   ", 8) != 0)) {
    mDiziRamDiag.Stage = 11; // initrd is not a raw FAT32 disk
    return;
  }
  // The current DIZI image is formatted with 512-byte FAT32 sectors.
  // Enforce BPB sanity before trusting the total-sector field.
  if ((Boot[11] != 0x00) || (Boot[12] != 0x02) ||
      (Boot[13] == 0) || ((Boot[13] & (Boot[13] - 1)) != 0) ||
      (Boot[13] > 128) || (Boot[16] == 0) ||
      ((Boot[14] | (Boot[15] << 8)) == 0)) {
    mDiziRamDiag.Stage = 12; // malformed BPB
    return;
  }
  TotalSectors = (UINT32)Boot[32] | ((UINT32)Boot[33] << 8) |
                 ((UINT32)Boot[34] << 16) | ((UINT32)Boot[35] << 24);
  FatBytes = (UINT64)TotalSectors * RAM_BLOCK_SIZE;
  if ((TotalSectors < 65536U) || (FatBytes > Available) ||
      (FatBytes > 512ULL * 1024 * 1024)) {
    mDiziRamDiag.Stage = 13; // FAT volume truncated or oversize
    return;
  }
  DEBUG ((DEBUG_WARN, "DIZI: initrd %lu bytes; bounded FAT32 %lu bytes; trailer %lu\\n",
          Available, FatBytes, Available - FatBytes));
'''
    code=once(code,old,new)
    code=once(code,
              "  mMedia.LastBlock        = (End - Start) / RAM_BLOCK_SIZE - 1;",
              "  mMedia.LastBlock        = TotalSectors - 1;")
    code=once(code,
              '  DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd block device 0x%lx size 0x%lx %r\\n", Start, End - Start, Status));',
              '  DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd FAT32 0x%lx size 0x%lx (source %lx) %r\\n", Start, FatBytes, Available, Status));')
    report={"path":str(RAM),"dry_run":dry_run,
            "condition":"only if FDT range contains complete sane FAT32 BPB volume",
            "rejects":["non-FAT32 blob","malformed BPB","truncated initrd","invalid bounds"],
            "read_only":True,"android_storage_writes":False,"xnu_boot_proven":False}
    if not dry_run: path.write_text(code)
    return report

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    ap.add_argument("--report",type=Path)
    args=ap.parse_args()
    data=patch(args.mu,args.dry_run)
    print(json.dumps(data,indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(data,indent=2)+"\n")
if __name__=="__main__":
    main()

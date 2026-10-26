#!/usr/bin/env python3
"""Recover an appended FAT32 from a Qualcomm LZ4-legacy vendor initrd.

On dizi, DXE sees 0x184C2102 at linux,initrd-start, the exact legacy LZ4
frame magic. The generic Android boot-v4 ramdisk is a verified raw FAT32,
so a possible layout is compressed vendor LZ4 bytes followed by raw FAT32.

Walk the LZ4 legacy frame headers by their *bounded compressed block sizes*
rather than scanning an arbitrary 8 MiB prefix. Only examine the resulting
boundary and at most 4096 trailing pad bytes; validate FAT32 BPB, its size,
and the EFI directory while allowing preceding FAT volume-label entries.

Never decompress unknown bytes, search unrelated physical RAM, write storage
or expose BlockIo for a candidate outside the DTB-provided initrd span.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

FILE=Path("External/UniXNU/package/UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.c")
MARKER="DIZI_FAT32_LZ4_LEGACY_PREFIX_V2"

def patch(root: Path, dry_run: bool = False) -> dict:
    file=root.resolve()/FILE
    s=file.read_text()
    if MARKER in s:
        raise ValueError("Already applied")
    if "DIZI_FAT32_BOUNDED_INITRD_V1" not in s:
        raise ValueError("Requires validated FAT32 BPB baseline")
    anchor='''  Boot = (UINT8 *)(UINTN)Start;
  if ((Boot[510] != 0x55) || (Boot[511] != 0xAA) ||
      (CompareMem (Boot + 82, "FAT32   ", 8) != 0)) {
    mDiziRamDiag.Stage = 11; // initrd is not a raw FAT32 disk
    return;
  }
'''
    replacement=r'''  Boot = (UINT8 *)(UINTN)Start;
  if ((Boot[510] != 0x55) || (Boot[511] != 0xAA) ||
      (CompareMem (Boot + 82, "FAT32   ", 8) != 0)) {
    UINT64 Offset;
    UINT64 ScanOffset;
    UINT64 SearchLimit;
    UINT64 CandidateBytes;
    UINT64 DataOffset;
    UINT64 RootBytes;
    UINT32 BlockSize;
    UINT32 CandidateSectors;
    UINT32 CandidateFatSectors;
    UINT32 CandidateReserved;
    UINT32 RootCluster;
    UINT32 RootEntryCount;
    UINT32 RootIndex;
    UINT32 PrefixMagic;
    UINT32 PrefixBlocks;
    UINT8 *Candidate;
    UINT8 *Dir;
    BOOLEAN Found = FALSE;
    BOOLEAN HasEfi;

    // DIZI_FAT32_LZ4_LEGACY_PREFIX_V2.
    // Only the valid DTB-provided initrd memory span is read. No writes.
    PrefixMagic = (UINT32)Boot[0] | ((UINT32)Boot[1] << 8) |
                  ((UINT32)Boot[2] << 16) | ((UINT32)Boot[3] << 24);
    mDiziRamDiag.Reserved = PrefixMagic;
    if (PrefixMagic != 0x184C2102U) {
      mDiziRamDiag.Stage = 11;
      return;
    }
    // Legacy LZ4: LE magic, then repeated LE compressed block sizes (up
    // to approximately the 8 MiB LZ4 block compression bound). A raw
    // FAT32 boot sector begins with a jump opcode, so its initial DWORD
    // cannot be a plausible compressed block length. Do not decompress
    // the vendor stream; simply locate the end of its framed blocks.
    Offset = 4;
    for (PrefixBlocks = 0; PrefixBlocks < 4096; ++PrefixBlocks) {
      if (Offset > Available || Available - Offset < 4) {
        break;
      }
      BlockSize = (UINT32)Boot[Offset] |
                  ((UINT32)Boot[Offset + 1] << 8) |
                  ((UINT32)Boot[Offset + 2] << 16) |
                  ((UINT32)Boot[Offset + 3] << 24);
      if (BlockSize == 0x184C2102U) {
        // Some vendor ramdisks concatenate multiple legacy frames.
        Offset += 4;
        continue;
      }
      if (BlockSize == 0U) {
        // An optional zero word terminates some Android legacy streams.
        Offset += 4;
        break;
      }
      if ((BlockSize > 8U * 1024 * 1024 + 65536U) ||
          (Available - Offset - 4 < BlockSize)) {
        break;
      }
      Offset += 4 + BlockSize;
    }

    mDiziRamDiag.Reserved = (UINT32)Offset;
    SearchLimit = Available - RAM_BLOCK_SIZE;
    if (Offset > SearchLimit) {
      mDiziRamDiag.Stage = 14;
      return;
    }
    if ((SearchLimit - Offset) > 4096) {
      SearchLimit = Offset + 4096; // bounded trailing alignment/padding
    }
    for (ScanOffset = Offset; ScanOffset <= SearchLimit; ++ScanOffset) {
      Candidate = Boot + (UINTN)ScanOffset;
      if (Candidate[510] != 0x55 || Candidate[511] != 0xAA ||
          CompareMem (Candidate + 82, "FAT32   ", 8) != 0 ||
          Candidate[11] != 0 || Candidate[12] != 2 ||
          Candidate[13] == 0 ||
          (Candidate[13] & (Candidate[13] - 1)) != 0 ||
          Candidate[13] > 128 ||
          Candidate[16] == 0 || Candidate[16] > 2) {
        continue;
      }

      CandidateReserved = (UINT32)Candidate[14] |
                          ((UINT32)Candidate[15] << 8);
      CandidateSectors = (UINT32)Candidate[32] |
                         ((UINT32)Candidate[33] << 8) |
                         ((UINT32)Candidate[34] << 16) |
                         ((UINT32)Candidate[35] << 24);
      CandidateFatSectors = (UINT32)Candidate[36] |
                            ((UINT32)Candidate[37] << 8) |
                            ((UINT32)Candidate[38] << 16) |
                            ((UINT32)Candidate[39] << 24);
      RootCluster = (UINT32)Candidate[44] |
                    ((UINT32)Candidate[45] << 8) |
                    ((UINT32)Candidate[46] << 16) |
                    ((UINT32)Candidate[47] << 24);
      CandidateBytes = (UINT64)CandidateSectors * RAM_BLOCK_SIZE;
      if (CandidateSectors < 65536U || CandidateReserved == 0 ||
          CandidateFatSectors == 0 || RootCluster < 2 ||
          CandidateBytes > Available - ScanOffset ||
          CandidateBytes > 512ULL * 1024 * 1024) {
        continue;
      }
      DataOffset = ((UINT64)CandidateReserved +
                    (UINT64)Candidate[16] * CandidateFatSectors +
                    ((UINT64)RootCluster - 2) * Candidate[13]) *
                   RAM_BLOCK_SIZE;
      RootBytes = (UINT64)Candidate[13] * RAM_BLOCK_SIZE;
      if (DataOffset > CandidateBytes ||
          RootBytes > CandidateBytes - DataOffset) {
        continue;
      }

      // mformat -v DIZIXNU may put a FAT volume label BEFORE 'EFI'.
      // Scan directory entries, skipping labels, deleted and VFAT LFN
      // slots, instead of requiring "EFI" at offset 0.
      Dir = Candidate + (UINTN)DataOffset;
      RootEntryCount = (UINT32)(RootBytes / 32);
      if (RootEntryCount > 128) RootEntryCount = 128;
      HasEfi = FALSE;
      for (RootIndex = 0; RootIndex < RootEntryCount; ++RootIndex) {
        UINT8 *Entry = Dir + 32 * RootIndex;
        if (Entry[0] == 0x00) break;
        if (Entry[0] == 0xE5 ||
            Entry[11] == 0x0F ||
            (Entry[11] & 0x08) != 0) continue;
        if (CompareMem (Entry, "EFI     ", 8) == 0 &&
            (Entry[11] & 0x10) != 0) {
          HasEfi = TRUE;
          break;
        }
      }
      if (!HasEfi) continue;

      Found = TRUE;
      DEBUG ((DEBUG_WARN,
              "DIZI: FAT32 found after legacy LZ4 at +0x%lx (%u blocks)\n",
              ScanOffset, PrefixBlocks));
      Start += ScanOffset;
      Available -= ScanOffset;
      Boot = Candidate;
      mDiziRamDiag.Reserved = (UINT32)ScanOffset;
      break;
    }
    if (!Found) {
      mDiziRamDiag.Stage = 14; // legacy LZ4 parsed, no validated FAT
      return;
    }
  }
'''
    if s.count(anchor)!=1:
        raise ValueError(f"pinned source anchor count: {s.count(anchor)}")
    s=s.replace(anchor,replacement)
    result={
        "marker":MARKER,
        "input_magic":"0x184C2102 (LZ4 legacy)",
        "algorithm":"walk legacy LZ4 compressed block lengths; test +0..4096 padding",
        "max_block_bytes":8*1024*1024+65536,
        "max_block_count":4096,
        "checks":"bounded FAT32 BPB + in-range sectors + first 128 root entries for EFI directory",
        "rejects_non_lz4":True,
        "new_failure_stage":14,
        "memory_only":True,
        "storage_writes":False,
        "hardware_verified":False,
        "dry_run":dry_run
    }
    if not dry_run:
        file.write_text(s)
    return result

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    ap.add_argument("--report",type=Path)
    a=ap.parse_args()
    data=patch(a.mu,a.dry_run)
    print(json.dumps(data,indent=2))
    if a.report:
        a.report.parent.mkdir(parents=True,exist_ok=True)
        a.report.write_text(json.dumps(data,indent=2)+"\n")

if __name__=="__main__":
    main()

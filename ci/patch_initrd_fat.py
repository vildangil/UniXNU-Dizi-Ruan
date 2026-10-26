#!/usr/bin/env python3
"""Public-only Dizi fix for Qualcomm's LZ4 legacy FDT initrd handoff.

UniXNU expects a raw FAT at the FDT /chosen initrd start, but Dizi reported
the LZ4 legacy magic 0x184C2102. For a combined vendor+generic ramdisk,
locate *our* 64 MiB FAT near the end of the FDT-defined memory range or
after a bounded legacy LZ4 block stream, validate its BPB and EFI root
directory, then expose just that validated range via read-only BlockIo.

If the generic ramdisk was not handed off by ABL, fail closed and show a
precise diagnostic in stock UniXNU's built-in fallback. No storage writes,
EFI boot order changes, physical memory scan outside the FDT initrd, or
external/private repository checkout is used.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path("External/UniXNU/package/UniXNUPkg")
RAM = ROOT / "Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.c"
CONFIG = ROOT / "Library/UniXNULib/Config.c"
MAGIC = "DIZI_FAT_AFTER_LZ4_V1"
GUID = """{ 0xb1d262e2, 0xc0bb, 0x49ef,
  { 0xa8, 0x2c, 0x5c, 0x26, 0x0e, 0x1b, 0x93, 0x43 } }"""


def once(src: str, needle: str, replacement: str, reason: str) -> str:
    count = src.count(needle)
    if count != 1:
        raise ValueError(f"{reason}: expected exactly one pinned anchor, found {count}")
    return src.replace(needle, replacement, 1)


def patch(root: Path, dry_run: bool = False) -> None:
    root = root.resolve()
    ram_path, cfg_path = root / RAM, root / CONFIG
    ram, cfg = ram_path.read_text(), cfg_path.read_text()
    if MAGIC in ram or MAGIC in cfg:
        raise ValueError("Dizi LZ4/FAT handoff already patched")

    # Status protocol created even on an unsuccessful driver entry. Visible
    # from the menu if the FAT volume does not get registered as SimpleFS.
    header = f"""// {MAGIC}: per-boot diagnostic only; not persisted in NVRAM.
STATIC CONST EFI_GUID mDiziRamStatusGuid = {GUID};
typedef struct {{
  UINT32 Stage;
  UINT32 FirstWord;
  UINT32 SpanMiB;
  UINT32 CandidateKiB;
}} DIZI_RAM_STATUS;
STATIC DIZI_RAM_STATUS mDiziRamStatus = {{ 0, 0, 0, 0 }};

#define DIZI_EXPECTED_FAT_BYTES  (64ULL * 1024 * 1024)
#define DIZI_TAIL_MARGIN        (256ULL * 1024)
#define DIZI_LEGACY_SCAN_BYTES  (64U * 1024)

STATIC
BOOLEAN
DiziCheckFat (
  IN CONST UINT8  *Base,
  IN UINT64       Available,
  IN UINT64       Offset,
  OUT UINT64      *FatBytes
  )
{{
  CONST UINT8 *Sector;
  CONST UINT8 *Root;
  UINT64      VolumeBytes;
  UINT64      RootOffset;
  UINT32      Sectors;
  UINT32      FatSectors;
  UINT32      Cluster;
  UINTN       I;
  UINT32      Reserved;
  UINT32      SectorsPerCluster;

  if (Offset > Available || Available - Offset < 512) return FALSE;
  Sector = Base + (UINTN)Offset;
  if (Sector[510] != 0x55 || Sector[511] != 0xAA ||
      CompareMem (Sector + 82, "FAT32   ", 8) != 0 ||
      Sector[11] != 0 || Sector[12] != 2) return FALSE;

  SectorsPerCluster = Sector[13];
  Reserved = Sector[14] | ((UINT32)Sector[15] << 8);
  if (SectorsPerCluster == 0 || SectorsPerCluster > 128 ||
      (SectorsPerCluster & (SectorsPerCluster - 1)) != 0 ||
      Reserved == 0 || Sector[16] == 0 || Sector[16] > 2) return FALSE;

  Sectors = (UINT32)Sector[32] | ((UINT32)Sector[33] << 8) |
            ((UINT32)Sector[34] << 16) | ((UINT32)Sector[35] << 24);
  FatSectors = (UINT32)Sector[36] | ((UINT32)Sector[37] << 8) |
               ((UINT32)Sector[38] << 16) | ((UINT32)Sector[39] << 24);
  Cluster = (UINT32)Sector[44] | ((UINT32)Sector[45] << 8) |
            ((UINT32)Sector[46] << 16) | ((UINT32)Sector[47] << 24);
  VolumeBytes = (UINT64)Sectors * 512;
  if (Sectors < 65536 || FatSectors == 0 || Cluster < 2 ||
      VolumeBytes != DIZI_EXPECTED_FAT_BYTES ||
      VolumeBytes > Available - Offset) return FALSE;

  RootOffset = ((UINT64)Reserved + (UINT64)Sector[16] * FatSectors +
                (UINT64)(Cluster - 2) * SectorsPerCluster) * 512;
  if (RootOffset > VolumeBytes ||
      (UINT64)SectorsPerCluster * 512 > VolumeBytes - RootOffset)
    return FALSE;

  Root = Sector + (UINTN)RootOffset;
  // mkfs.fat may place its DIZIUEFI volume-label entry before EFI.
  for (I = 0; I < (UINTN)SectorsPerCluster * 512 / 32 && I < 128; ++I) {{
    CONST UINT8 *Entry = Root + I * 32;
    if (Entry[0] == 0) break;
    if (Entry[0] == 0xE5 || Entry[11] == 0x0F ||
        (Entry[11] & 0x08) != 0) continue;
    if (CompareMem (Entry, "EFI     ", 8) == 0 &&
        (Entry[11] & 0x10) != 0) {{
      *FatBytes = VolumeBytes;
      return TRUE;
    }}
  }}
  return FALSE;
}}

STATIC
BOOLEAN
DiziFindFatAfterLz4 (
  IN UINT8   *Base,
  IN UINT64  Available,
  OUT UINT8  **FatBase,
  OUT UINT64 *FatBytes
  )
{{
  UINT64 Tail, Begin, Limit, Offset;
  UINT32 BlockBytes;
  UINTN  Count;
  UINTN  Pad;

  if (Available < 512) return FALSE;
  // First, permit the generic ramdisk to be the full FDT range.
  if (DiziCheckFat (Base, Available, 0, FatBytes)) {{
    *FatBase = Base;
    return TRUE;
  }}
  if (Available < DIZI_EXPECTED_FAT_BYTES) return FALSE;

  // ABL often appends the generic boot.img ramdisk at the end of the
  // vendor LZ4 data. Match only our 64 MiB FAT with 256 KiB of padding.
  Tail = Available - DIZI_EXPECTED_FAT_BYTES;
  Begin = Tail > DIZI_TAIL_MARGIN ? Tail - DIZI_TAIL_MARGIN : 0;
  Limit = Tail + DIZI_TAIL_MARGIN;
  if (Limit > Available - 512) Limit = Available - 512;
  for (Offset = Begin; Offset <= Limit; ++Offset) {{
    if (DiziCheckFat (Base, Available, Offset, FatBytes)) {{
      *FatBase = Base + (UINTN)Offset;
      return TRUE;
    }}
  }}

  // Legacy LZ4: magic, then 32-bit lengths followed by compressed blocks.
  // This scans block *headers* only, not a speculative memory range.
  if (Base[0] != 0x02 || Base[1] != 0x21 ||
      Base[2] != 0x4C || Base[3] != 0x18) return FALSE;
  Offset = 4;
  for (Count = 0; Count < 4096; ++Count) {{
    if (Offset > Available || Available - Offset < 4) break;
    BlockBytes = (UINT32)Base[Offset] | ((UINT32)Base[Offset+1] << 8) |
                 ((UINT32)Base[Offset+2] << 16) | ((UINT32)Base[Offset+3] << 24);
    if (BlockBytes == 0x184C2102U) {{ Offset += 4; continue; }}
    if (BlockBytes == 0) {{ Offset += 4; break; }}
    if (BlockBytes > 8U*1024*1024+65536U ||
        BlockBytes > Available-Offset-4) break;
    Offset += (UINT64)BlockBytes + 4;
  }}

  // An aligned generic FAT can follow a framed vendor ramdisk. Never
  // examine beyond FDT-reported initrd; test at most 64 KiB padding.
  for (Pad = 0; Pad <= DIZI_LEGACY_SCAN_BYTES; ++Pad) {{
    if (Offset > Available || Pad > Available - Offset) break;
    if (DiziCheckFat (Base, Available, Offset + Pad, FatBytes)) {{
      *FatBase = Base + (UINTN)(Offset + Pad);
      return TRUE;
    }}
  }}
  return FALSE;
}}
"""
    ram = once(ram, "#define RAM_BLOCK_SIZE  512",
               header + "\n#define RAM_BLOCK_SIZE  512", "driver helper insertion")
    ram = once(ram,
        '  UINT64      End;\n  EFI_HANDLE  Handle;',
        '  UINT64      End;\n  UINT64      FatBytes;\n  UINT8       *FatBase;\n  UINT64      Available;\n  EFI_HANDLE  Handle;',
        "PublishInitrd variables")
    ram = once(ram,
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no /chosen\\n"));',
        '    mDiziRamStatus.Stage = 3;\n'
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no /chosen\\n"));',
        "FDT chosen failure")
    ram = once(ram,
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no initrd in /chosen\\n"));',
        '    mDiziRamStatus.Stage = 4;\n'
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no initrd in /chosen\\n"));',
        "FDT initrd missing")
    anchor = '''  if ((End <= Start) || (((End - Start) % RAM_BLOCK_SIZE) != 0)) {
    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd 0x%lx-0x%lx is not a whole number of sectors\\n", Start, End));
    return;
  }

  mRamBase                = (UINT8 *)(UINTN)Start;'''
    replacement = '''  if (End <= Start || End - Start < 512 || End - Start > 512ULL * 1024 * 1024) {
    mDiziRamStatus.Stage = 5; // invalid or unexpectedly large FDT initrd
    return;
  }
  Available = End - Start;
  mDiziRamStatus.SpanMiB = (UINT32)(Available / (1024 * 1024));
  mDiziRamStatus.FirstWord =
    *(CONST UINT32 *)(UINTN)Start;
  if (!DiziFindFatAfterLz4 ((UINT8 *)(UINTN)Start, Available,
                            &FatBase, &FatBytes)) {
    mDiziRamStatus.Stage = Available < DIZI_EXPECTED_FAT_BYTES ? 6 : 7;
    return;
  }
  mDiziRamStatus.Stage = 8; // candidate validated; registration pending
  mDiziRamStatus.CandidateKiB =
    (UINT32)(((UINTN)FatBase - (UINTN)Start) / 1024);

  mRamBase                = FatBase;'''
    ram = once(ram, anchor, replacement, "validate and find FAT32 range")
    ram = once(ram,
        "  mMedia.LastBlock        = (End - Start) / RAM_BLOCK_SIZE - 1;",
        "  mMedia.LastBlock        = FatBytes / RAM_BLOCK_SIZE - 1;",
        "BlockIo correct FAT length")
    ram = once(ram,
        '  DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: initrd block device 0x%lx size 0x%lx %r\\n", Start, End - Start, Status));',
        '''  mDiziRamStatus.Stage = EFI_ERROR (Status) ? 9 : 10;
  DEBUG ((DEBUG_ERROR, "DIZI: bounded FAT at %p, %lu bytes, BlockIo %r\\n",
          FatBase, FatBytes, Status));''',
        "published BlockIo stage")
    ram = once(ram,
        '  Hob = GetFirstGuidHob (&mEntryArgHobGuid);',
        '''  EFI_HANDLE StatusHandle = NULL;
  // Expose diagnostics only to this boot's EFI protocol database.
  (VOID)gBS->InstallProtocolInterface (
    &StatusHandle, (EFI_GUID *)&mDiziRamStatusGuid,
    EFI_NATIVE_INTERFACE, &mDiziRamStatus
  );
  Hob = GetFirstGuidHob (&mEntryArgHobGuid);''',
        "diagnostic protocol install")
    ram = once(ram,
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no entry argument HOB\\n"));',
        '    mDiziRamStatus.Stage = 1;\n'
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: no entry argument HOB\\n"));',
        "HOB failure")
    ram = once(ram,
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: x0 0x%lx is not a device tree\\n", Dtb));',
        '    mDiziRamStatus.Stage = 2;\n'
        '    DEBUG ((DEBUG_ERROR, "UNIXNURAMDISK: x0 0x%lx is not a device tree\\n", Dtb));',
        "invalid DTB")

    cfg = once(cfg, '#define UNIXNU_ARCH_NAME        "AARCH64"',
        f'''// {MAGIC}: inspect read-only RAM driver state on fallback screen.
STATIC CONST EFI_GUID mDiziRamStatusGuid = {GUID};
typedef struct {{
  UINT32 Stage;
  UINT32 FirstWord;
  UINT32 SpanMiB;
  UINT32 CandidateKiB;
}} DIZI_RAM_STATUS;

STATIC
VOID
DiziRamNotice (OUT CHAR8 *Notice, IN UINTN Size)
{{
  DIZI_RAM_STATUS *Info = NULL;
  EFI_STATUS Status;
  CONST CHAR8 *State;
  Status = gBS->LocateProtocol ((EFI_GUID *)&mDiziRamStatusGuid,
                                NULL, (VOID **)&Info);
  if (EFI_ERROR (Status) || Info == NULL) {{
    AsciiSPrint (Notice, Size, "DIZI: RAM DXE not started");
    return;
  }}
  switch (Info->Stage) {{
    case 1: State = "no-HOB"; break;
    case 2: State = "bad-FDT"; break;
    case 3: State = "no-chosen"; break;
    case 4: State = "no-initrd"; break;
    case 5: State = "invalid-span"; break;
    case 6: State = "LZ4-short-span"; break;
    case 7: State = "LZ4-no-FAT"; break;
    case 8: State = "FAT-valid"; break;
    case 9: State = "BlockIo-error"; break;
    case 10: State = "FAT-published-noFS"; break;
    default: State = "unknown"; break;
  }}
  AsciiSPrint (Notice, Size, "DIZI: %a / %uMiB / %08x",
              State, Info->SpanMiB, Info->FirstWord);
}}

#define UNIXNU_ARCH_NAME        "AARCH64"''',
        "UniXNU diagnostic function")
    cfg = once(cfg,
        '      AsciiStrCpyS (Config->Notice, sizeof (Config->Notice), "no boot entry found");',
        '       DiziRamNotice (Config->Notice, sizeof (Config->Notice));',
        "fallback diagnostic")
    if not dry_run:
        ram_path.write_text(ram)
        cfg_path.write_text(cfg)
    print(("CHECK " if dry_run else "PATCH ") + str(ram_path.relative_to(root)))
    print(("CHECK " if dry_run else "PATCH ") + str(cfg_path.relative_to(root)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    patch(args.mu, args.dry_run)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Bridge the known DIZI PMIC/SPMI key sampler to the stock UniXNU menu.

Build-time overlay only, no NVRAM/partition changes. Uses the same read-only
PMIC sampler and observer-channel commands as the working R3 selector.
It does not claim those inputs work until verified on actual hardware.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

LIB = Path("External/UniXNU/package/UniXNUPkg/Library/UniXNULib")
SRC = Path("Platforms/Xiaomi/DiziBootPkg/BootSelector")
MODULES = (
    "DiziPmicKeys.c", "DiziPmicKeys.h",
    "DiziSpmiArbProbe.c", "DiziSpmiArbProbe.h", "DiziSpmiArbRead.c",
)
MARKER = "DIZI_UNIXNU_PMIC_BRIDGE"


def once(s: str, before: str, after: str, title: str) -> str:
    n = s.count(before)
    if n != 1:
        raise ValueError(f"{title}: expected one match, got {n}: {before[:50]!r}")
    return s.replace(before, after, 1)


def patch(mu: Path, dry_run: bool = False) -> dict:
    mu = mu.resolve()
    menu_path = mu / LIB / "Menu.c"
    inf_path = mu / LIB / "UniXNULib.inf"
    config_path = mu / LIB / "Config.c"
    code = menu_path.read_text()
    inf = inf_path.read_text()
    config = config_path.read_text()
    if MARKER in code:
        raise ValueError("UniXNU PMIC bridge already present")
    for module in MODULES:
        if not (mu / SRC / module).is_file():
            raise FileNotFoundError(mu / SRC / module)

    boilerplate = """// DIZI_UNIXNU_PMIC_BRIDGE: use the same real board PMIC/arbiter
// poller as the R3 recovery selector. Only supported one-byte key reads.
#include "Dizi/DiziPmicKeys.h"

STATIC DIZI_PMIC_KEYS mDiziKeys;
STATIC DIZI_SPMI_ARB_PROBE mDiziArb;
STATIC BOOLEAN mDiziInit;
STATIC UINT32 mDiziTick;

STATIC
VOID
DiziKeysInitialize (VOID)
{
  EFI_INPUT_KEY Key;
  BOOLEAN Pressed;
  if (mDiziInit) return;
  mDiziInit = TRUE;
  ZeroMem (&mDiziKeys, sizeof (mDiziKeys));
  ZeroMem (&mDiziArb, sizeof (mDiziArb));
  DiziProbeSpmiArbiterReadOnly (&mDiziArb);
  DiziPmicSampleKeys (&mDiziKeys, &mDiziArb, mDiziTick++, &Key, &Pressed);
}

STATIC
BOOLEAN
DiziKeysAvailable (VOID)
{
  DiziKeysInitialize ();
  return mDiziKeys.SpmiAvailable || mDiziKeys.ArbiterAvailable ||
         (mDiziKeys.PonValid && mDiziKeys.GpioValid);
}

// Wait on the standard EFI input plus read-only physical PMIC polling.
STATIC
EFI_STATUS
DiziWaitConfirmedKey (OUT EFI_INPUT_KEY *Key)
{
  EFI_EVENT Timer = NULL;
  EFI_EVENT Wait[2];
  UINTN Count, Index;
  EFI_STATUS Status;
  BOOLEAN Pressed;

  DiziKeysInitialize ();
  Status = gBS->CreateEvent (EVT_TIMER, TPL_CALLBACK, NULL, NULL, &Timer);
  if (EFI_ERROR (Status)) return Status;
  Status = gBS->SetTimer (Timer, TimerPeriodic, EFI_TIMER_PERIOD_MILLISECONDS (100));
  if (EFI_ERROR (Status)) {
    gBS->CloseEvent (Timer);
    return Status;
  }
  Wait[0] = Timer;
  Count = 1;
  if (gST->ConIn != NULL) Wait[Count++] = gST->ConIn->WaitForKey;

  for (;;) {
    Status = gBS->WaitForEvent (Count, Wait, &Index);
    if (EFI_ERROR (Status)) break;
    if (Index == 0) {
      Pressed = FALSE;
      DiziPmicSampleKeys (&mDiziKeys, &mDiziArb, mDiziTick++, Key, &Pressed);
      if (Pressed) { Status = EFI_SUCCESS; break; }
    } else if (!EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, Key))) {
      Status = EFI_SUCCESS;
      break;
    }
  }
  gBS->CloseEvent (Timer);
  return Status;
}

"""
    code = once(code, "#include \"Internal.h\"\n",
                "#include \"Internal.h\"\n\n" + boilerplate,
                "PMIC helpers include")
    code = once(code, "  BOOLEAN        HasInput;\n",
                "  BOOLEAN        HasInput;\n  BOOLEAN        DiziPressed;\n",
                "main-loop PMIC state")
    code = once(code, "  Count    = Config->EntryCount;\n",
                "  DiziKeysInitialize ();\n  Count    = Config->EntryCount;\n",
                "PMIC initial probe")
    code = once(code, "  HasInput = (CountInputDevices () > 0);",
                "  HasInput = (CountInputDevices () > 0) || DiziKeysAvailable ();",
                "physical-input detection")
    code = once(code, "    Previous = Selected;\n    if (Signaled == 0) {",
                "    Previous = Selected;\n"
                "    DiziPressed = FALSE;\n"
                "    if (Signaled == 0) {\n"
                "      DiziPmicSampleKeys (&mDiziKeys, &mDiziArb, mDiziTick++, &Key, &DiziPressed);\n"
                "      if (!DiziPressed) {",
                "PMIC timer sampling")
    code = once(code, "      }\n    } else {\n      if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {",
                "      }\n      }\n    } else {\n"
                "      if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {",
                "main menu timer branch closure")
    code = once(code, """      if (!UserActive) {
        //
        // The first key takes over:""", """      DiziPressed = TRUE;
    }
    if (DiziPressed) {
      if (!UserActive) {
        //
        // The first key takes over:""", "unified PMIC/EFI key")
    # After main menu keyboard logic, there is a matching closing brace.
    code = once(code, """        break;
      }
    }

    if (Selected != Previous)""",
                """        break;
      }
    }

    if (Selected != Previous)""", "main-loop closure check") if False else code
    # Original 'else' branch already closed by the last '}' after key
    # handling. We inserted a second nested if, so the closing brace is
    # consumed by the unified block: balance stays the same.
    code = once(code, """  if ((gST->ConIn == NULL) || (CountInputDevices () == 0)) {
    UniXNULog ("menu: confirmation needs an input device, cancelled");""",
                """  if (((gST->ConIn == NULL) || (CountInputDevices () == 0)) &&
      !DiziKeysAvailable ()) {
    UniXNULog ("menu: confirmation needs an input device, cancelled");""",
                "confirmation accepts PMIC")
    code = once(code, "  UINTN          Index;\n  UINTN          Shown;",
                "  UINTN          Shown;", "unused confirmation index")
    code = once(code, """    if (EFI_ERROR (gBS->WaitForEvent (1, &gST->ConIn->WaitForKey, &Index))) {
      return FALSE;
    }

    if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
      continue;
    }""",
                """    if (EFI_ERROR (DiziWaitConfirmedKey (&Key))) {
      return FALSE;
    }""", "confirmation physical key wait")
    code = once(code,
                """    if ((Key.UnicodeChar == CHAR_CARRIAGE_RETURN) || (Key.UnicodeChar == CHAR_LINEFEED)) {""",
                """    if ((Key.UnicodeChar == CHAR_CARRIAGE_RETURN) ||
        (Key.UnicodeChar == CHAR_LINEFEED) || (Key.ScanCode == SCAN_SUSPEND)) {""",
                "Power key confirms")
    # Internal.h provides BaseMemoryLib / BootServices; IoLib needed for read-only arbiter.
    inf = once(inf, "  MemoryAllocationLib\n", "  MemoryAllocationLib\n  IoLib\n",
               "board SPMI IoLib")
    inf = once(inf, "  Menu.c\n", "  Menu.c\n" +
               "".join("  Dizi/" + item + "\n" for item in MODULES if item.endswith(".c")),
               "board input C files")
    # The previous "BlockIo 122 / FS 6" counts all UFS partitions; it
    # does not establish whether the *UniXNU RAM disk* was published.
    # Match only UniXNURamDiskDxe's vendor device path GUID and read its
    # boot sector using the installed EFI_BLOCK_IO_PROTOCOL. This probe
    # does no direct physical-memory reads or storage writes.
    config = once(config, "#include <Library/FdtLib.h>",
                  "#include <Library/FdtLib.h>\n"
                  "#include <Protocol/BlockIo.h>\n"
                  "#include <Protocol/DevicePath.h>",
                  "DIZI RAM driver protocol headers")
    config = once(
        config, "#define UNIXNU_ARCH_NAME",
        """// DIZI_UNIXNU_RAM_FAT_PROBE: read-only verification of the exact
// UniXNURamDiskDxe vendor handle, never the numerous Qualcomm UFS disks.
STATIC CONST EFI_GUID mDiziRamVendorGuid = {
  0xA9C6827C, 0x1BD8, 0x410C,
  { 0x88, 0x5A, 0xC4, 0x65, 0x00, 0xF7, 0xD8, 0x36 }
};

// Same in-memory GUID as DIZI_RAM_DIAG_PROTOCOL_V1 in UniXNURamDiskDxe.
// Unlike the vendor block GUID it exists even on early DXE failure.
STATIC CONST EFI_GUID mDiziRamDiagGuid = {
  0x3ea6eac1, 0x9556, 0x4f49,
  { 0xa1, 0x0b, 0xfc, 0x87, 0x42, 0x6d, 0x63, 0x48 }
};
typedef struct { UINT32 Stage; UINT32 Reserved; } DIZI_RAM_DIAG;
STATIC CHAR8 mDiziNotFatDetail[32];

STATIC
CONST CHAR8 *
DiziRamFatState (VOID)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0;
  UINTN Index;
  EFI_STATUS Status;
  DIZI_RAM_DIAG *Diag = NULL;
  CONST CHAR8 *Result = "absent";
  Status = gBS->LocateProtocol ((EFI_GUID *)&mDiziRamDiagGuid,
                                NULL, (VOID **)&Diag);
  if (EFI_ERROR (Status) || Diag == NULL) return "DXE-not-run";
  switch (Diag->Stage) {
    case 1: return "DXE-entered";
    case 2: return "no-HOB";
    case 3: return "bad-HOB";
    case 4: return "bad-DTB";
    case 5: return "no-chosen";
    case 6: return "no-initrd";
    case 7: return "unaligned";
    case 8: return "BlockIo-err";
    case 9: break;
    case 10: return "no-BlockIo";
    case 11:
      AsciiSPrint (mDiziNotFatDetail, sizeof (mDiziNotFatDetail),
                   "notFAT:%08x", Diag->Reserved);
      return mDiziNotFatDetail;
    case 12: return "invalid-FAT-BPB";
    case 13: return "FAT-truncated";
    case 14:
      AsciiSPrint (mDiziNotFatDetail, sizeof (mDiziNotFatDetail),
                   "LZ4-noFAT:%08x", Diag->Reserved);
      return mDiziNotFatDetail;
    default: return "unknown-stage";
  }
  Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiBlockIoProtocolGuid, NULL, &Count, &Handles
                  );
  if (EFI_ERROR (Status)) return "no BlockIo";
  for (Index = 0; Index < Count; ++Index) {
    EFI_DEVICE_PATH_PROTOCOL *Path = DevicePathFromHandle (Handles[Index]);
    EFI_BLOCK_IO_PROTOCOL *Io = NULL;
    UINTN PathLen;
    UINT8 Boot[512];
    EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *Fs = NULL;
    if (Path == NULL || Path->Type != HARDWARE_DEVICE_PATH ||
        Path->SubType != HW_VENDOR_DP) continue;
    PathLen = (UINTN)Path->Length[0] | ((UINTN)Path->Length[1] << 8);
    if (PathLen < sizeof (VENDOR_DEVICE_PATH)) continue;
    if (!CompareGuid (&((VENDOR_DEVICE_PATH *)Path)->Guid, &mDiziRamVendorGuid)) continue;
    Result = "registered";
    Status = gBS->HandleProtocol (Handles[Index], &gEfiBlockIoProtocolGuid, (VOID **)&Io);
    if (EFI_ERROR (Status) || Io == NULL || Io->Media == NULL ||
        !Io->Media->MediaPresent || Io->Media->BlockSize != 512) {
      Result = "bad-media";
      break;
    }
    Status = Io->ReadBlocks (Io, Io->Media->MediaId, 0, sizeof (Boot), Boot);
    if (EFI_ERROR (Status)) {
      Result = "read-error";
      break;
    }
    if (Boot[510] != 0x55 || Boot[511] != 0xAA ||
        CompareMem (Boot + 82, "FAT32   ", 8) != 0) {
      Result = "not-FAT32";
      break;
    }
    // FAT driver may install SimpleFS on either the parent or a child.
    // FAT32-noFS is a useful hint, not a definitive failure verdict.
    Result = "FAT32-noFS";
    if (!EFI_ERROR (gBS->HandleProtocol (Handles[Index],
          &gEfiSimpleFileSystemProtocolGuid, (VOID **)&Fs))) {
      Result = "FAT32+FS";
    }
    break;
  }
  if (Handles != NULL) FreePool (Handles);
  return Result;
}

#define UNIXNU_ARCH_NAME""",
        "read-only UniXNU RAM disk probe"
    )
    config = once(config,
                  '      AsciiStrCpyS (Config->Notice, sizeof (Config->Notice), "no boot entry found");',
                  '''      {
        EFI_HANDLE *BlockHandles = NULL;
        EFI_HANDLE *FatHandles = NULL;
        UINTN BlockCount = 0;
        UINTN FatCount = 0;
        CONST CHAR8 *RamState = DiziRamFatState ();
        if (!EFI_ERROR (gBS->LocateHandleBuffer (ByProtocol,
              &gEfiBlockIoProtocolGuid, NULL, &BlockCount, &BlockHandles)) &&
            BlockHandles != NULL) {
          FreePool (BlockHandles);
        }
        if (!EFI_ERROR (gBS->LocateHandleBuffer (ByProtocol,
              &gEfiSimpleFileSystemProtocolGuid, NULL, &FatCount, &FatHandles)) &&
            FatHandles != NULL) {
          FreePool (FatHandles);
        }
        AsciiSPrint (Config->Notice, sizeof (Config->Notice),
                     "DIZI RAM %a / Block %u / FS %u",
                     RamState, (UINT32)BlockCount, (UINT32)FatCount);
        UniXNULog ("config: DIZI ram disk %a, BlockIo %u, FS %u",
                   RamState, (UINT32)BlockCount, (UINT32)FatCount);
      }''',
                  "on-screen targeted DIZI RAM/FAT diagnostic")
    report = {
        "menu": "Upstream UniXNU Menu.c (original graphics and layout)",
        "buttons": "R3 PMIC/SPMI probe bridged into UniXNU menu and confirmation",
        "no_boot_diagnostic": "precise driver/HOB/FDT/initrd state, FAT32 sector, BlockIo and FS counts",
        "original_r3_source_changed": False,
        "read_only_storage": True,
        "hardware_tested": False,
        "dry_run": dry_run,
    }
    if not dry_run:
        subdir = mu / LIB / "Dizi"
        subdir.mkdir(parents=True, exist_ok=True)
        for module in MODULES:
            shutil.copy2(mu / SRC / module, subdir / module)
        menu_path.write_text(code)
        inf_path.write_text(inf)
        config_path.write_text(config)
    return report


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mu", type=Path)
    cli.add_argument("--dry-run", action="store_true")
    cli.add_argument("--report", type=Path)
    opts = cli.parse_args()
    result = patch(opts.mu, dry_run=opts.dry_run)
    print(json.dumps(result, indent=2))
    if opts.report:
        opts.report.parent.mkdir(parents=True, exist_ok=True)
        opts.report.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()

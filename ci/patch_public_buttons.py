#!/usr/bin/env python3
"""Dizi firmware-menu input V2: poll existing EFI TextIn and TextInEx.

Native Dizi Mu-Silicium's selector handles both UEFI protocols and PMIC input.
The public standalone UniXNU build stays on its pinned baseline; this patch
repairs only the EFI input consumer and adds visible key-source diagnostics.
Do not add vendor PMIC drivers, fake protocols, MMIO reads, flash writes, or
speculative key scan codes. Always operate on the isolated CI checkout.
"""
from __future__ import annotations

import argparse
from pathlib import Path

MENU = Path("External/UniXNU/package/UniXNUPkg/Library/UniXNULib/Menu.c")
INF = Path("External/UniXNU/package/UniXNUPkg/Library/UniXNULib/UniXNULib.inf")
MARK = "DIZI_EFI_BUTTON_POLL_V2"


def once(source: str, old: str, new: str, what: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{what}: expected one pinned anchor, found {count}")
    return source.replace(old, new, 1)


HELPERS = r'''// DIZI_EFI_BUTTON_POLL_V2: polling only already-installed UEFI input handles.
STATIC
UINTN
DiziCountInputHandles (IN EFI_GUID *Protocol)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0;
  if (EFI_ERROR (gBS->LocateHandleBuffer (
                       ByProtocol, Protocol, NULL, &Count, &Handles))) {
    return 0;
  }
  if (Handles != NULL) {
    FreePool (Handles);
  }
  return Count;
}

// Poll every timer tick, regardless of WaitForKey/WaitForKeyEx signaling.
// Prefer the standard console so one key never fires twice; physical EX
// devices can exist outside the ConSplitter. No PMIC MMIO is accessed.
STATIC
BOOLEAN
DiziPollEfiKey (OUT EFI_INPUT_KEY *Key, OUT CONST CHAR8 **Origin)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0;
  UINTN Index;
  EFI_STATUS Status;
  EFI_SIMPLE_TEXT_INPUT_EX_PROTOCOL *Ex;
  EFI_SIMPLE_TEXT_INPUT_PROTOCOL *Basic;
  EFI_KEY_DATA Data;

  if (Key == NULL || Origin == NULL) return FALSE;
  *Origin = "NONE";

  if (gST->ConIn != NULL && gST->ConIn->ReadKeyStroke != NULL &&
      !EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, Key))) {
    *Origin = "CON";
    return TRUE;
  }

  Status = gBS->LocateHandleBuffer (ByProtocol,
                                    &gEfiSimpleTextInputExProtocolGuid,
                                    NULL, &Count, &Handles);
  if (!EFI_ERROR (Status) && Handles != NULL) {
    for (Index = 0; Index < Count && Index < 64; ++Index) {
      if (Handles[Index] == gST->ConsoleInHandle) continue;
      Ex = NULL;
      Status = gBS->HandleProtocol (Handles[Index],
                                    &gEfiSimpleTextInputExProtocolGuid,
                                    (VOID **)&Ex);
      if (EFI_ERROR (Status) || Ex == NULL || Ex->ReadKeyStrokeEx == NULL)
        continue;
      if (!EFI_ERROR (Ex->ReadKeyStrokeEx (Ex, &Data))) {
        *Key = Data.Key;
        *Origin = "EX";
        FreePool (Handles);
        return TRUE;
      }
    }
    FreePool (Handles);
  }

  Handles = NULL;
  Count = 0;
  Status = gBS->LocateHandleBuffer (ByProtocol,
                                    &gEfiSimpleTextInProtocolGuid,
                                    NULL, &Count, &Handles);
  if (!EFI_ERROR (Status) && Handles != NULL) {
    for (Index = 0; Index < Count && Index < 64; ++Index) {
      if (Handles[Index] == gST->ConsoleInHandle) continue;
      Basic = NULL;
      Status = gBS->HandleProtocol (Handles[Index],
                                    &gEfiSimpleTextInProtocolGuid,
                                    (VOID **)&Basic);
      if (EFI_ERROR (Status) || Basic == NULL ||
          Basic == gST->ConIn || Basic->ReadKeyStroke == NULL) continue;
      if (!EFI_ERROR (Basic->ReadKeyStroke (Basic, Key))) {
        *Origin = "TEXT";
        FreePool (Handles);
        return TRUE;
      }
    }
    FreePool (Handles);
  }
  return FALSE;
}

STATIC
VOID
DiziShowInputStatus (IN UNIXNU_UI *Ui, IN CONST CHAR8 *Origin,
                     IN CONST EFI_INPUT_KEY *Key)
{
  CHAR16 Line[128];
  UnicodeSPrint (Line, sizeof (Line),
                 L"Input EFI:%u EX:%u  %a scan:%04x char:%04x",
                 (UINT32)DiziCountInputHandles (&gEfiSimpleTextInProtocolGuid),
                 (UINT32)DiziCountInputHandles (&gEfiSimpleTextInputExProtocolGuid),
                 Origin,
                 Key != NULL ? (UINT32)Key->ScanCode : 0,
                 Key != NULL ? (UINT32)Key->UnicodeChar : 0);
  UniXNUUiDrawStatus (Ui, 1, Line);
}

// The confirmation submenu must not block on ConIn->WaitForKey either.
// Return EFI_TIMEOUT after 30 s rather than trapping the user.
STATIC
EFI_STATUS
DiziWaitEfiKey (OUT EFI_INPUT_KEY *Key)
{
  EFI_STATUS Status;
  EFI_EVENT Timer = NULL;
  UINTN Signaled;
  UINTN Tick;
  CONST CHAR8 *Origin;
  Status = gBS->CreateEvent (EVT_TIMER, TPL_CALLBACK, NULL, NULL, &Timer);
  if (EFI_ERROR (Status)) return Status;
  Status = gBS->SetTimer (Timer, TimerPeriodic,
                           EFI_TIMER_PERIOD_MILLISECONDS (100));
  if (EFI_ERROR (Status)) {
    gBS->CloseEvent (Timer);
    return Status;
  }
  Status = EFI_TIMEOUT;
  for (Tick = 0; Tick < 300; ++Tick) {
    if (EFI_ERROR (gBS->WaitForEvent (1, &Timer, &Signaled))) {
      Status = EFI_DEVICE_ERROR;
      break;
    }
    if (DiziPollEfiKey (Key, &Origin)) {
      Status = EFI_SUCCESS;
      break;
    }
  }
  gBS->SetTimer (Timer, TimerCancel, 0);
  gBS->CloseEvent (Timer);
  return Status;
}

'''


def patch(root: Path, dry_run: bool = False) -> None:
    root = root.resolve()
    menu_path, inf_path = root / MENU, root / INF
    src, inf = menu_path.read_text(), inf_path.read_text()
    if MARK in src or MARK in inf or "DIZI_EFI_BUTTON_FALLBACK_V1" in src:
        raise ValueError("Dizi button input already patched; use clean pinned checkout")

    src = once(src, '#include "Internal.h"\n',
               '#include "Internal.h"\n#include <Protocol/SimpleTextInEx.h>\n\n'
               + HELPERS, "input helper insertion")
    src = once(src, "  EFI_EVENT      Events[2];\n  UINTN          EventCount;\n",
               "", "drop ConIn event wait variables")
    src = once(src, "  BOOLEAN        UserActive;\n",
               "  BOOLEAN        UserActive;\n"
               "  BOOLEAN        DiziGotKey;\n"
               "  CONST CHAR8   *DiziKeySource;\n", "input state")
    src = once(src, "  HasInput = (CountInputDevices () > 0);",
               "  HasInput = (CountInputDevices () > 0) ||\n"
               "             (DiziCountInputHandles (&gEfiSimpleTextInputExProtocolGuid) > 0);",
               "EX availability")
    src = once(
        src,
        '''  UniXNUUiDrawStatus (
    Ui,
    1,
    HasInput ? L"Up/Down: select    Enter: boot    1-9: boot entry    Esc: stop timer"
             : L"No input device: the default entry boots when the timer ends"
    );''',
        '  DiziShowInputStatus (Ui, "NONE", NULL);',
        "show on-screen input counters",
    )
    src = once(src,
               '''  EventCount = 0;
  Events[EventCount++] = Timer;
  if (gST->ConIn != NULL) {
    Events[EventCount++] = gST->ConIn->WaitForKey;
  }

''', "", "timer-only wait")
    src = once(src,
               "    Status = gBS->WaitForEvent (EventCount, Events, &Signaled);",
               "    Status = gBS->WaitForEvent (1, &Timer, &Signaled);",
               "timer-only WaitForEvent")
    src = once(src,
               "    Previous = Selected;\n    if (Signaled == 0) {",
               "    Previous = Selected;\n"
               "    DiziGotKey = DiziPollEfiKey (&Key, &DiziKeySource);\n"
               "    if (!DiziGotKey) {",
               "poll EFI input on every tick")
    src = once(src,
               '''    } else {
      if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
        continue;
      }

      if (!UserActive) {''',
               '''    } else {
      DiziShowInputStatus (Ui, DiziKeySource, &Key);
      if (!UserActive) {''',
               "unify timer and physical input")
    src = once(src,
               "if ((Key.ScanCode == SCAN_UP) || (Key.UnicodeChar == L'k'))",
               "if ((Key.ScanCode == SCAN_UP) || (Key.ScanCode == SCAN_VOLUME_UP) ||"
               " (Key.UnicodeChar == L'k'))",
               "Volume Up scans")
    src = once(src,
               "if ((Key.ScanCode == SCAN_DOWN) || (Key.UnicodeChar == L'j'))",
               "if ((Key.ScanCode == SCAN_DOWN) || (Key.ScanCode == SCAN_VOLUME_DOWN) ||"
               " (Key.UnicodeChar == L'j'))",
               "Volume Down scans")

    # Original confirmation routine blocks on ConIn even if navigation uses EX.
    src = once(src,
               "  UINTN          Index;\n  UINTN          Shown;",
               "  UINTN          Drain;\n  CONST CHAR8   *DiziKeySource;\n  UINTN          Shown;",
               "confirmation variable")
    src = once(src,
               '''  if ((gST->ConIn == NULL) || (CountInputDevices () == 0)) {
    UniXNULog ("menu: confirmation needs an input device, cancelled");''',
               '''  if (DiziCountInputHandles (&gEfiSimpleTextInProtocolGuid) == 0 &&
      DiziCountInputHandles (&gEfiSimpleTextInputExProtocolGuid) == 0) {
    UniXNULog ("menu: confirmation needs an input device, cancelled");''',
               "confirmation protocol detection")
    src = once(src,
               '''  while (!EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
  }''',
               '''  for (Drain = 0; Drain < 16 &&
       DiziPollEfiKey (&Key, &DiziKeySource); ++Drain) {
  }''',
               "bounded confirmation key flush")
    src = once(src,
               '''    if (EFI_ERROR (gBS->WaitForEvent (1, &gST->ConIn->WaitForKey, &Index))) {
      return FALSE;
    }

    if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
      continue;
    }''',
               '''    if (EFI_ERROR (DiziWaitEfiKey (&Key))) {
      return FALSE;
    }''',
               "confirmation EX/timer input")
    src = once(src,
               '''    if ((Key.UnicodeChar == CHAR_CARRIAGE_RETURN) || (Key.UnicodeChar == CHAR_LINEFEED)) {''',
               '''    if ((Key.UnicodeChar == CHAR_CARRIAGE_RETURN) ||
        (Key.UnicodeChar == CHAR_LINEFEED) ||
        (Key.ScanCode == SCAN_SUSPEND)) {''',
               "power confirmation")

    inf = once(inf,
               "  gEfiSimpleTextInProtocolGuid      ## SOMETIMES_CONSUMES",
               "  gEfiSimpleTextInProtocolGuid      ## SOMETIMES_CONSUMES\n"
               "  gEfiSimpleTextInputExProtocolGuid ## SOMETIMES_CONSUMES",
               "EX INF protocol GUID")
    if not dry_run:
        menu_path.write_text(src)
        inf_path.write_text(inf)
    print(("CHECK " if dry_run else "PATCH ") + str(MENU))
    print(("CHECK " if dry_run else "PATCH ") + str(INF))


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mu", type=Path)
    cli.add_argument("--dry-run", action="store_true")
    opts = cli.parse_args()
    patch(opts.mu, opts.dry_run)


if __name__ == "__main__":
    main()

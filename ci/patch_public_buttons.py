#!/usr/bin/env python3
"""Restore Dizi UniXNU input from already installed *public* EFI protocols.

The pinned public Mu-Silicium includes Qualcomm ButtonsDxe and attempts to
attach its SimpleTextIn handles to ConIn. Some drivers may publish a physical
SimpleTextIn device but not reach ConSplitter. Poll those EFI handles every
100 ms independently of gST->ConIn, using only ReadKeyStroke. Do not invent
PMIC register access, enable black-screen-prone SPMIDxe/PmicDxeLa, or
reproduce code from private experimental repositories.
"""
from __future__ import annotations
import argparse
from pathlib import Path

MENU=Path("External/UniXNU/package/UniXNUPkg/Library/UniXNULib/Menu.c")
MARK="DIZI_EFI_BUTTON_FALLBACK_V1"

def once(s:str, before:str, after:str, what:str)->str:
    count=s.count(before)
    if count!=1: raise ValueError(f"{what}: expected 1 pinned anchor, found {count}")
    return s.replace(before,after,1)

def patch(root:Path,dry_run:bool=False)->None:
    file=root.resolve()/MENU
    s=file.read_text()
    if MARK in s: raise ValueError("Already patched")
    helper="""// DIZI_EFI_BUTTON_FALLBACK_V1: read keys only from existing EFI
// SimpleTextIn handles. This does not touch PMIC MMIO or firmware variables.
STATIC
BOOLEAN
DiziReadExistingPhysicalKey (OUT EFI_INPUT_KEY *Key)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0;
  UINTN Index;
  BOOLEAN Found = FALSE;
  EFI_STATUS Status;
  EFI_SIMPLE_TEXT_INPUT_PROTOCOL *Input = NULL;

  if (Key == NULL) return FALSE;
  Status = gBS->LocateHandleBuffer (ByProtocol,
                                    &gEfiSimpleTextInProtocolGuid,
                                    NULL, &Count, &Handles);
  if (EFI_ERROR (Status) || Handles == NULL) return FALSE;
  for (Index = 0; Index < Count; ++Index) {
    // Never consume the ConSplitter key stream twice.
    if (Handles[Index] == gST->ConsoleInHandle) continue;
    Input = NULL;
    Status = gBS->HandleProtocol (Handles[Index],
                                 &gEfiSimpleTextInProtocolGuid,
                                 (VOID **)&Input);
    if (EFI_ERROR (Status) || Input == NULL ||
        Input->ReadKeyStroke == NULL) continue;
    if (!EFI_ERROR (Input->ReadKeyStroke (Input, Key))) {
      Found = TRUE;
      break;
    }
  }
  gBS->FreePool (Handles);
  return Found;
}

"""
    s=once(s,'#include "Internal.h"\n','#include "Internal.h"\n\n'+helper,
           "helper insertion")
    s=once(s,'  BOOLEAN        UserActive;\n',
           '  BOOLEAN        UserActive;\n  BOOLEAN        DiziPhysicalKey;\n',
           "key state variable")
    s=once(s,
           '    Previous = Selected;\n    if (Signaled == 0) {',
           '    Previous = Selected;\n'
           '    DiziPhysicalKey = FALSE;\n'
           '    if (Signaled == 0) {\n'
           '      DiziPhysicalKey = DiziReadExistingPhysicalKey (&Key);\n'
           '      if (!DiziPhysicalKey) {',
           "poll on timer")
    s=once(s,
           '''      }
    } else {
      if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {''',
           '''      }
      }
    } else {
      if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {''',
           "close timer-only branch")
    s=once(s,
           '''      if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
        continue;
      }

      if (!UserActive) {''',
           '''      if (EFI_ERROR (gST->ConIn->ReadKeyStroke (gST->ConIn, &Key))) {
        continue;
      }
      DiziPhysicalKey = TRUE;
    }

    if (DiziPhysicalKey) {
      if (!UserActive) {''',
           "unify existing hardware and ConIn events")
    if not dry_run:file.write_text(s)
    print(("CHECK " if dry_run else "PATCH ")+str(MENU))

def main()->None:
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mu",type=Path)
    cli.add_argument("--dry-run",action="store_true")
    o=cli.parse_args()
    patch(o.mu,o.dry_run)

if __name__=="__main__":main()

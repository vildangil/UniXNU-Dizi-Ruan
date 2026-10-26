#!/usr/bin/env python3
"""Pass the ARM64 firmware entry x0 to UniXNURamDiskDxe via a GUID HOB.

Mu-Silicium's stock SEC replaces x0 before entering C and never publishes
the FDT pointer. Preserve the ABL/BootShim entry x0 in callee-saved x19
before firmware initialization. Once HOB memory exists, hand its UINT64
value to the DXE RamDisk driver under UniXNU's exact pinned GUID.

No guessed FDT address, static physical memory scratch slot, NVRAM write,
partition write or modification to the persistent Mu-Silicium checkout.
"""
from __future__ import annotations
import argparse
from pathlib import Path

ASM=Path("Silicon/Silicium/SiliciumPkg/Sec/AArch64/ModuleEntryPoint.S")
C=Path("Silicon/Silicium/SiliciumPkg/Sec/Sec.c")
MARK="DIZI_ENTRY_ARG_HOB_V1"


def once(s:str, before:str, after:str, title:str)->str:
    count=s.count(before)
    if count!=1:
        raise ValueError(f"{title}: expected exactly one pinned anchor; found {count}")
    return s.replace(before,after,1)


def patch(root:Path,dry_run:bool=False)->None:
    root=root.resolve()
    asmfile, cfile=root/ASM,root/C
    a=asmfile.read_text()
    c=cfile.read_text()
    if MARK in a or MARK in c:
        raise ValueError("SEC entry handoff already patched")

    a=once(a, "ASM_FUNC (_ModuleEntryPoint)\n  // Do Platform Specific Initialization",
        "ASM_FUNC (_ModuleEntryPoint)\n"
        "  // DIZI_ENTRY_ARG_HOB_V1: preserve original x0 across SEC setup.\n"
        "  // x19 is callee-saved in AAPCS64; no memory address is guessed.\n"
        "  mov   x19, x0\n"
        "  // Do Platform Specific Initialization",
        "preserve entry x0")
    a=once(a,'''  // Set Jump Location
  ldr   x0, =ASM_PFX (SecEntry)

  // Clear Frame Pointer
  mov   x29, xzr

  // Jump to C Code
  blr   x0
''','''  // Set Jump Location (x0 holds the preserved entry argument).
  ldr   x16, =ASM_PFX (SecEntry)

  // Clear Frame Pointer
  mov   x29, xzr
  mov   x0, x19

  // Jump to C Code
  blr   x16
''',"ARM64 entry parameter to C")
    guid='''// Same GUID as UniXNURamDiskDxe/mEntryArgHobGuid, UINT64 data.
STATIC CONST EFI_GUID mDiziEntryArgHobGuid = {
  0xDAEE82E6, 0x8090, 0x4E72,
  { 0xBF, 0xB9, 0x78, 0xC1, 0x3C, 0xD4, 0xE3, 0x59 }
};

'''
    c=once(c, '#include "Sec.h"\n', '#include "Sec.h"\n\n'+guid,
           "HOB GUID declaration")
    c=once(c,'SecMain (VOID)\n{','SecMain (IN UINT64 EntryArg)\n{',
           "SEC main argument")
    c=once(c,'''  // Build CPU HOB
  BuildCpuHob (ArmGetPhysicalAddressBits (), PcdGet8 (PcdPrePiCpuIoSize));''',
        '''  // DIZI_ENTRY_ARG_HOB_V1: HOB memory is initialized above.
  // Keep the exact ABL x0 value for the UniXNU FDT driver; the driver
  // validates the DTB magic/header before dereferencing initrd properties.
  (VOID)BuildGuidDataHob (&mDiziEntryArgHobGuid, &EntryArg, sizeof (EntryArg));

  // Build CPU HOB
  BuildCpuHob (ArmGetPhysicalAddressBits (), PcdGet8 (PcdPrePiCpuIoSize));''',
        "publish x0 GUID HOB")
    c=once(c,'SecEntry (VOID)\n{','SecEntry (IN UINT64 EntryArg)\n{',
           "SEC C entry accepts argument")
    c=once(c,'  SecMain ();\n','  SecMain (EntryArg);\n',"forward entry to main")
    if not dry_run:
        asmfile.write_text(a)
        cfile.write_text(c)
    for p in [ASM,C]:
        print(("CHECK " if dry_run else "PATCH ")+str(p))


def main()->None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mu",type=Path)
    parser.add_argument("--dry-run",action="store_true")
    opts=parser.parse_args()
    patch(opts.mu,opts.dry_run)


if __name__=="__main__":main()

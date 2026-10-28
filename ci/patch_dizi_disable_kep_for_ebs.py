#!/usr/bin/env python3
"""Dizi-only reversible NO-XNU test: disable the Windows KEP EBS hook.

The real 2026-10-28 hardware PC 0xFC366EAC was matched byte-for-byte to
MdeModulePkg/Universal/BdsDxe/BdsDxe.efi in the *same CI firmware volume*:
BdsDxe image base=0xFC363000, KEP hook RVA=0x3E3C,
faulting RVA=0x3EAC, instruction 0xB900012A (str w10,[x9]).
The pinned Mu-Silicium source calls PatchTransferToKernel there, which
writes a self-modifying ARM64 BL into mTargetInstructionAddr.

Disable just the KernelErrataPatcherLibConstructor event registration, in the
disposable CI checkout ONLY, to preserve firmware EBS flow/callbacks while
removing KEP's Windows-specific AllocatePages/ExitBootServices hooks.
No normal EDK2 or sm7435 drivers are altered.
"""
from __future__ import annotations
import argparse
from pathlib import Path

TARGET = "Silicon/Silicium/SiliciumPkg/Library/KernelErrataPatcherLib/KernelErrataPatcherLib.c"
MARK = "DIZI_NO_KEP_EBS_HOOK_V1"
ENTRY = """KernelErrataPatcherLibConstructor (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE *SystemTable)
{
"""
PATCH = """KernelErrataPatcherLibConstructor (
  IN EFI_HANDLE        ImageHandle,
  IN EFI_SYSTEM_TABLE *SystemTable)
{
  // DIZI_NO_KEP_EBS_HOOK_V1 (NO-XNU ONLY, CI checkout only).
  // This library targets Windows winload. Do not register its ReadyToBoot
  // event and do not replace gBS->AllocatePages or gBS->ExitBootServices.
  // The unmodified DXE Core callback chain remains enabled.
  return EFI_SUCCESS;
"""

def apply(mu: Path, dry_run: bool) -> None:
    p = mu.resolve() / TARGET
    src = p.read_text()
    if MARK in src:
        raise ValueError("KEP bypass already applied")
    if src.count(ENTRY) != 1:
        raise ValueError("Pinned KEP constructor anchor missing/ambiguous")
    for anchor in (
        "gBS->ExitBootServices = KepExitBootServicesHook;",
        "gBS->AllocatePages    = KepAllocatePagesHook;",
        "PatchTransferToKernel (mWinloadBase, mWinloadLength, ShellCode, ShellCodeSize);",
        "Status = gBS->CreateEventEx (EVT_NOTIFY_SIGNAL, TPL_CALLBACK, ReadyToBootHandler",
        "return gBS->ExitBootServices (ImageHandle, MapKey);",
    ):
        if src.count(anchor) != 1:
            raise ValueError("Pinned KEP hook implementation changed: " + anchor)
    out = src.replace(ENTRY, PATCH, 1)
    if out.count(MARK) != 1:
        raise ValueError("KEP bypass insertion count differs")
    # Fail closed if an unrelated source path is accidentally selected.
    if not dry_run:
        p.write_text(out)
    print(("CHECK" if dry_run else "PATCH"),p,
          "KEP constructor exits before ReadyToBoot event registration; NO XNU")

if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    ns=ap.parse_args()
    apply(ns.mu,ns.dry_run)

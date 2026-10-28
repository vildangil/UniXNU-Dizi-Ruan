#!/usr/bin/env python3
"""Dizi-only core ExitBootServices visual trace in disposable Mu_Basecore.

The historical tablet screen showed an EFI synchronous exception after
DarwinBoot's yellow before-ExitBootServices marker at PC 0xFC368EAC.
Instrument the *actual pinned DXE core* without changing EBS semantics.
At most 12 colored 12px-high retained bands are painted on the known
1600x2560, 32-bit, 6400-byte-stride frame buffer at 0xB0000000.

Each band is retained, so the last completed color is a durable checkpoint.
This is a diagnostic only; never install on an ordinary EFI/Android image.
"""
from __future__ import annotations
import argparse
from pathlib import Path

TARGET = "Mu_Basecore/MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c"
MARK = "DIZI_DXE_CORE_EBS_TRACE_V1"

# The stages are keyed to unique text in mu_basecore's pinned DxeMain.c.
# The insertions precede the anchor. A marker before a failing call remains
# visible and the next marker is absent.
STAGES = [
    ("    CoreNotifySignalList (&gEfiEventBeforeExitBootServicesGuid);",
     "    DiziCoreEbsMark (0, 0xFFFFA500); // 0 ORANGE before BeforeExit callbacks\n"),
    ("    mExitBootServicesCalled = TRUE;",
     "    DiziCoreEbsMark (1, 0xFF00CED1); // 1 CYAN after BeforeExit callbacks\n"),
    ("  gTimer->SetTimerPeriod (gTimer, 0);",
     "  DiziCoreEbsMark (2, 0xFF40E0D0); // 2 PALE CYAN before timer stop\n"),
    ("  Status = CoreTerminateMemoryMap (MapKey);",
     "  DiziCoreEbsMark (3, 0xFF00FF00); // 3 GREEN before terminate memory map\n"),
    ("  gMemoryMapTerminated = TRUE;",
     "  DiziCoreEbsMark (4, 0xFF008000); // 4 DARK GREEN after memory map term\n"),
    ("  CoreNotifySignalList (&gEfiEventExitBootServicesGuid);",
     "  DiziCoreEbsMark (5, 0xFF0080FF); // 5 BLUE before ExitBootServices callbacks\n"),
    ("  REPORT_STATUS_CODE (\n    EFI_PROGRESS_CODE,\n    (EFI_SOFTWARE_EFI_BOOT_SERVICE | EFI_SW_BS_PC_EXIT_BOOT_SERVICES)",
     "  DiziCoreEbsMark (6, 0xFF9932CC); // 6 PURPLE after ExitBootServices callbacks\n"),
    ("  MemoryProtectionExitBootServicesCallback ();",
     "  DiziCoreEbsMark (7, 0xFFFF00FF); // 7 MAGENTA before memory protection callback\n"),
    ("  SaveAndSetDebugTimerInterrupt (FALSE);",
     "  DiziCoreEbsMark (8, 0xFFFFFFFF); // 8 WHITE after memory protection callback\n"),
    ("  gCpu->DisableInterrupt (gCpu);",
     "  DiziCoreEbsMark (9, 0xFFFF0000); // 9 RED before CPU IRQ disable\n"),
    ("  gDxeCoreST->BootServices        = NULL;",
     "  DiziCoreEbsMark (10, 0xFFFFFF00); // 10 YELLOW after disable IRQ\n"),
    ("  return Status;\n}\n\n/**\n  Given a compressed source buffer",
     "  DiziCoreEbsMark (11, 0xFF00FF66); // 11 LIME EBS completed, before return\n"),
]

HELPER = """// DIZI_DXE_CORE_EBS_TRACE_V1
// Dizi observed 1600x2560 GOP: framebuffer base 0xB0000000, stride 6400,
// 32bpp. Uses only volatile stores, no EFI service, allocation, output or
// firmware protocol, including after exit from boot services.
// Each numbered row persists. 0..1 BeforeExit callbacks, 2 timer,
// 3..4 memory map, 5..6 ExitBootServices callbacks, 7..8 memory protection,
// 9..10 CPU interrupts, 11 successful return.
STATIC VOID DiziCoreEbsMark (UINTN Stage, UINT32 Color)
{
  volatile UINT32 *Fb;
  UINTN X, Y;
  if (Stage >= 12) { return; }
  Fb = (volatile UINT32 *)(UINTN)0xB0000000ULL;
  for (Y = 84 + Stage * 12; Y < 84 + (Stage + 1) * 12; ++Y) {
    for (X = 0; X < 960; ++X) {
      Fb[Y * 1600 + X] = Color;
    }
  }
  __asm__ __volatile__ ("dsb sy" ::: "memory");
}

"""

ENTRY = "EFI_STATUS\nEFIAPI\nCoreExitBootServices (\n"
def apply(mu: Path, dry_run: bool):
    target=mu.resolve()/TARGET
    src=target.read_text()
    if MARK in src:
        raise ValueError("DXE core trace patch already applied")
    if src.count(ENTRY)!=1:
        raise ValueError("Pinned CoreExitBootServices function changed")
    prefix, rem=src.split(ENTRY,1)
    # Ensure only the specific ExitBootServices function is touched.
    ending="\n}\n\n/**\n  Given a compressed source buffer"
    if ending not in rem:
        raise ValueError("Pinned ExitBootServices function end changed")
    function, rest=rem.split(ending,1)
    for anchor, insert in STAGES[:-1]:
        if function.count(anchor)!=1:
            raise ValueError(f"DXE EBS stage anchor changed/ambiguous: {anchor!r}")
        function=function.replace(anchor, insert+anchor,1)
    # Prepend to the original final 'return Status;' without altering logic.
    fragment="\n  return Status;"
    if function.count(fragment)!=1:
        raise ValueError("Expected exact one final return from EBS")
    function=function.replace(fragment,
        "\n  DiziCoreEbsMark (11, 0xFF00FF66); // 11 LIME EBS completed, before return"
        + fragment,1)
    if function.count("DiziCoreEbsMark (11,")!=1:
        raise ValueError("Expected exactly one EBS return trace marker")
    out=prefix+HELPER+ENTRY+function+ending+rest
    if function.count("DiziCoreEbsMark (")!=12:
        raise ValueError("Expected twelve unique EBS mark calls")
    if out.count("CoreNotifySignalList (&gEfiEventExitBootServicesGuid);")!=1:
        raise ValueError("EXIT_BOOT_SERVICES dispatch missing")
    if not dry_run:
        target.write_text(out)
    print(("CHECK" if dry_run else "PATCH"),target,
          "12 retained DXE core EBS stage markers, original callbacks intact")

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu",type=Path)
    ap.add_argument("--dry-run",action="store_true")
    opts=ap.parse_args()
    apply(opts.mu,opts.dry_run)

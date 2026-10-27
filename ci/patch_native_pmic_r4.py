#!/usr/bin/env python3
"""Bridge pinned native Dizi R4 PMIC key sampler into public UniXNU V2 menu.

Only changes files in the isolated build workspace. The R4 C/H sources
must have been extracted from the exact Mu-Silicium R4 commit in CI.
Preserves EFI TextIn/TextInEx as primary input and displays PMIC diagnostics.
SPMI observer performs a bounded READ command write to its CMD register;
never flashes or writes PMIC data registers. Not hardware validated.
"""
from __future__ import annotations

import argparse
from pathlib import Path

LIB = Path("External/UniXNU/package/UniXNUPkg/Library/UniXNULib")
R4 = ("DiziPmicKeys.c", "DiziPmicKeys.h", "DiziSpmiArbProbe.c",
      "DiziSpmiArbProbe.h", "DiziSpmiArbRead.c")
MARK = "DIZI_R4_PMIC_BRIDGE_V1"


def once(s: str, before: str, after: str, label: str) -> str:
    n = s.count(before)
    if n != 1:
        raise ValueError(f"{label}: expected one match, got {n}")
    return s.replace(before, after, 1)


HELPERS = r"""// DIZI_R4_PMIC_BRIDGE_V1: R4 SM7435 PON / GPIO button sampler.
// DiziSpmiArbRead.c sends one bounded observer-channel SPMI READ
// command; it does NOT write PMIC data registers.
#include "Dizi/DiziPmicKeys.h"

STATIC DIZI_PMIC_KEYS       mDiziPmic;
STATIC DIZI_SPMI_ARB_PROBE mDiziArb;
STATIC UINT32              mDiziPmicTick;
STATIC BOOLEAN             mDiziPmicStarted;

// Probe the R4 mapped hardware exactly once, in normal DXE context.
STATIC
VOID
DiziR4Start (VOID)
{
  EFI_INPUT_KEY Unused;
  BOOLEAN Pressed;
  if (mDiziPmicStarted) return;
  mDiziPmicStarted = TRUE;
  ZeroMem (&mDiziPmic, sizeof (mDiziPmic));
  ZeroMem (&mDiziArb, sizeof (mDiziArb));
  DiziProbeSpmiArbiterReadOnly (&mDiziArb);
  DiziPmicSampleKeys (&mDiziPmic, &mDiziArb,
                      mDiziPmicTick++, &Unused, &Pressed);
}

STATIC
BOOLEAN
DiziPollR4PmicKey (OUT EFI_INPUT_KEY *Key)
{
  BOOLEAN Pressed = FALSE;
  if (!mDiziPmicStarted) return FALSE;
  DiziPmicSampleKeys (&mDiziPmic, &mDiziArb,
                      mDiziPmicTick++, Key, &Pressed);
  return Pressed;
}

// Alternate the mapping and raw readout every second. A single status
// line is used so the menu still fits the portrait device screen.
// "R:" values are raw Qualcomm SPMI error codes, not UEFI status codes.
STATIC
VOID
DiziR4DrawStatus (IN UNIXNU_UI *Ui)
{
  CHAR16 Line[128];
  if (((mDiziPmicTick / 10U) & 1U) == 0U) {
    UnicodeSPrint (
      Line, sizeof (Line),
      L"SPMI v:%08x APIDs:%u P:%u/%u G:%u/%u",
      mDiziArb.Version, mDiziArb.ApidCount,
      mDiziArb.PonMapped ? 1U : 0U, mDiziArb.PonApid,
      mDiziArb.GpioMapped ? 1U : 0U, mDiziArb.GpioApid
    );
  } else {
    UnicodeSPrint (
      Line, sizeof (Line),
      L"PON:%02x R:%x DN:%u PWR:%u GPIO:%02x R:%x UP:%u",
      mDiziPmic.PonRaw, mDiziPmic.PonResult,
      mDiziPmic.VolDown ? 1U : 0U,
      mDiziPmic.PowerDown ? 1U : 0U,
      mDiziPmic.GpioRaw, mDiziPmic.GpioResult,
      mDiziPmic.VolUp ? 1U : 0U
    );
  }
  UniXNUUiDrawStatus (Ui, 2, Line);
}

"""


def patch(root: Path, dry_run: bool = False) -> None:
    root = root.resolve()
    menu_file = root / LIB / "Menu.c"
    inf_file = root / LIB / "UniXNULib.inf"
    r4_path = root / LIB / "Dizi"
    menu = menu_file.read_text()
    inf = inf_file.read_text()

    if "DIZI_EFI_BUTTON_POLL_V2" not in menu:
        raise ValueError("Apply EFI input V2 before the native R4 bridge")
    if MARK in menu or MARK in inf:
        raise ValueError("Native R4 bridge already patched")

    sources = {name: (r4_path / name).read_text() for name in R4}
    if ("DIZI_PON_GEN3_RESIN_MASK 0x40U" not in sources["DiziPmicKeys.c"]
        or "DIZI_PON_GEN3_POWER_MASK 0x80U" not in sources["DiziPmicKeys.c"]
        or "DIZI_SPMI_TIMEOUT_US 1000U" not in sources["DiziSpmiArbRead.c"]
        or sources["DiziSpmiArbRead.c"].count("MmioWrite32 (") != 1
        or "DiziProbeSpmiArbiterReadOnly" not in sources["DiziSpmiArbProbe.c"]):
        raise ValueError("The pinned native R4 sources failed safety audit")

    menu = once(
        menu,
        '#include <Protocol/SimpleTextInEx.h>\n',
        '#include <Protocol/SimpleTextInEx.h>\n\n' + HELPERS,
        "R4 helper insertion",
    )
    menu = once(
        menu,
        "  Count    = Config->EntryCount;",
        "  DiziR4Start ();\n  Count    = Config->EntryCount;",
        "R4 initialization",
    )
    menu = once(
        menu,
        "             (DiziCountInputHandles (&gEfiSimpleTextInputExProtocolGuid) > 0);",
        "             (DiziCountInputHandles (&gEfiSimpleTextInputExProtocolGuid) > 0) ||\n"
        "             (mDiziPmic.PonValid && mDiziPmic.GpioValid);",
        "R4 physical input availability",
    )
    menu = once(
        menu,
        "    DiziGotKey = DiziPollEfiKey (&Key, &DiziKeySource);\n"
        "    if (!DiziGotKey) {",
        "    DiziGotKey = DiziPollEfiKey (&Key, &DiziKeySource);\n"
        "    if (!DiziGotKey) {\n"
        "      DiziGotKey = DiziPollR4PmicKey (&Key);\n"
        "      if (DiziGotKey) DiziKeySource = \"PMIC\";\n"
        "    } else {\n"
        "      // Keep the R4 sampler running even during USB/EFI activity.\n"
        "      EFI_INPUT_KEY Unused;\n"
        "      (VOID)DiziPollR4PmicKey (&Unused);\n"
        "    }\n"
        "    if ((mDiziPmicTick % 10U) == 0U) DiziR4DrawStatus (Ui);\n"
        "    if (!DiziGotKey) {",
        "R4 key delivery and diagnostic",
    )
    menu = once(
        menu,
        "    if (DiziPollEfiKey (Key, &Origin)) {\n"
        "      Status = EFI_SUCCESS;\n"
        "      break;\n"
        "    }",
        "    if (DiziPollEfiKey (Key, &Origin) || DiziPollR4PmicKey (Key)) {\n"
        "      Status = EFI_SUCCESS;\n"
        "      break;\n"
        "    }",
        "confirmation R4 polling",
    )

    inf = once(
        inf,
        "  Menu.c\n",
        "  Menu.c\n"
        "  Dizi/DiziPmicKeys.c\n"
        "  Dizi/DiziSpmiArbProbe.c\n"
        "  Dizi/DiziSpmiArbRead.c\n",
        "R4 INF source modules",
    )
    inf = once(
        inf,
        "  FdtLib\n",
        "  FdtLib\n  IoLib\n",
        "R4 MMIO IoLib",
    )

    if not dry_run:
        menu_file.write_text(menu)
        inf_file.write_text(inf)
    print(("CHECK " if dry_run else "PATCH ") + str(menu_file.relative_to(root)))
    print(("CHECK " if dry_run else "PATCH ") + str(inf_file.relative_to(root)))


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mu", type=Path)
    cli.add_argument("--dry-run", action="store_true")
    args = cli.parse_args()
    patch(args.mu, args.dry_run)


if __name__ == "__main__":
    main()

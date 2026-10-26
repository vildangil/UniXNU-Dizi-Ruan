#!/usr/bin/env python3
"""Protect UniXNU menu from false PMK8350 RESIN / Volume Down transitions.

This modifies only the copied R3 key integration in UniXNULib, not the
working R3 recovery boot selector. Requires neutral release for >=1.6 s
and a persistent asserted state for >=0.6 s before acting on Volume Down.
No PMIC writes, no firmware variables, no new driver binding.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

MENU=Path("External/UniXNU/package/UniXNUPkg/Library/UniXNULib/Menu.c")
MARKER="DIZI_VOLUME_DOWN_RELEASE_GUARD_V1"

def once(s, before, after, name):
    n=s.count(before)
    if n!=1: raise ValueError(f"{name}: expected 1 occurrence, got {n}")
    return s.replace(before,after,1)

def patch(mu:Path,dry_run:bool=False)->dict:
    path=mu.resolve()/MENU
    code=path.read_text()
    if "DIZI_UNIXNU_PMIC_BRIDGE" not in code: raise ValueError("first apply native UniXNU PMIC bridge")
    if MARKER in code: raise ValueError("deglitch already installed")
    guard = """// DIZI_VOLUME_DOWN_RELEASE_GUARD_V1: a spurious or latched
// PMK8350 RESIN status must never scroll the boot menu.
// Only an explicit release followed by a long, stable new press counts.
STATIC UINTN mDiziDownReleaseSamples;
STATIC UINTN mDiziDownAssertSamples;
STATIC BOOLEAN mDiziDownArmed;
STATIC BOOLEAN mDiziDownPending;

STATIC
VOID
DiziPmicSampleKeysGuarded (OUT EFI_INPUT_KEY *Key, OUT BOOLEAN *Pressed)
{
  UINT32 Tick;
  BOOLEAN RawPressed;

  Tick = mDiziTick++;
  RawPressed = FALSE;
  DiziPmicSampleKeys (&mDiziKeys, &mDiziArb, Tick, Key, &RawPressed);
  *Pressed = RawPressed;

  // R3 hardware poller runs only on even ticks at 100ms menu cadence.
  // Never count an unsampled tick as a physical button release.
  if ((Tick & 1U) == 0 && mDiziKeys.PonValid && mDiziKeys.GpioValid) {
    if (!mDiziKeys.VolDown) {
      if (mDiziDownReleaseSamples < 8) ++mDiziDownReleaseSamples;
      if (mDiziDownReleaseSamples >= 8) mDiziDownArmed = TRUE;
      mDiziDownPending = FALSE;
      mDiziDownAssertSamples = 0;
    } else {
      mDiziDownReleaseSamples = 0;
      if (mDiziDownPending) {
        if (mDiziDownAssertSamples < 3) ++mDiziDownAssertSamples;
        if (mDiziDownAssertSamples >= 3) {
          Key->ScanCode = SCAN_DOWN;
          Key->UnicodeChar = 0;
          *Pressed = TRUE;
          mDiziDownPending = FALSE;
          mDiziDownArmed = FALSE;
        }
      }
    }
  }

  if (RawPressed && Key->ScanCode == SCAN_DOWN) {
    // Do not use raw R3 edge in the menu until additional samples agree.
    if (mDiziDownArmed && !mDiziDownPending) {
      mDiziDownPending = TRUE;
      mDiziDownAssertSamples = 0;
      mDiziDownArmed = FALSE;
    }
    *Pressed = FALSE;
  }
}

"""
    code=once(code, "STATIC\nBOOLEAN\nDiziKeysAvailable (VOID)",guard+"STATIC\nBOOLEAN\nDiziKeysAvailable (VOID)","guard insertion")
    code=once(code,
        "DiziPmicSampleKeys (&mDiziKeys, &mDiziArb, mDiziTick++, Key, &Pressed);",
        "DiziPmicSampleKeysGuarded (Key, &Pressed);","confirmation polling")
    code=once(code,
        "DiziPmicSampleKeys (&mDiziKeys, &mDiziArb, mDiziTick++, &Key, &DiziPressed);",
        "DiziPmicSampleKeysGuarded (&Key, &DiziPressed);","menu polling")
    result={
        "patch":MARKER,"dry_run":dry_run,"sample_interval_ms":200,
        "require_released_samples":8,"extra_asserted_samples":3,
        "initially_armed":False,"affects":"UniXNU menu PMIC Volume Down only",
        "hardware_verified":False, "device_writes":False}
    if not dry_run: path.write_text(code)
    return result

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("mu",type=Path)
    cli.add_argument("--dry-run",action="store_true")
    cli.add_argument("--report",type=Path)
    args=cli.parse_args()
    data=patch(args.mu,args.dry_run)
    print(json.dumps(data,indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(data,indent=2)+"\n")
if __name__=="__main__": main()

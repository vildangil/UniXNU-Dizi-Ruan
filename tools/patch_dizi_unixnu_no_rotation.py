#!/usr/bin/env python3
"""DIZI native UniXNU UI: prevent phantom downward highlight from auto-rotate.

UniXNU enters 'no input device' mode when EFI ConIn and PMIC are not seen,
then rotates the highlighted fallback menu entry while the countdown runs.
On dizi this is misleadingly indistinguishable from Volume Down. Do not
automatically rotate at all; keep the safe exit selected until real input.
"""
import argparse
import json
from pathlib import Path

MENU = Path("External/UniXNU/package/UniXNUPkg/Library/UniXNULib/Menu.c")
MARKER = "DIZI_UNIXNU_NO_AUTOROTATE_V1"

def patch(root:Path,dry_run:bool=False)->dict:
    file=root.resolve()/MENU
    text=file.read_text()
    if MARKER in text: raise ValueError("Already patched")
    if "DIZI_UNIXNU_PMIC_BRIDGE" not in text: raise ValueError("Apply PMIC bridge first")
    anchor='''  if (!HasInput && (RotateMs == 0)) {
    RotateMs = DEFAULT_ROTATE_SEC * 1000;
  }

  UniXNUUiDrawFrame (Ui, Config);'''
    replace='''  if (!HasInput && (RotateMs == 0)) {
    RotateMs = DEFAULT_ROTATE_SEC * 1000;
  }
  // DIZI_UNIXNU_NO_AUTOROTATE_V1: never rotate a firmware menu without
  // a physical key; no-input auto-rotation looked like a stuck Volume Down.
  RotateMs = 0;

  UniXNUUiDrawFrame (Ui, Config);'''
    if text.count(anchor)!=1: raise ValueError("Unexpected pinned UniXNU Menu.c rotation code")
    text=text.replace(anchor,replace)
    report={"auto_rotate":False,"default_entry":"return","physical_input_unchanged":True,
            "reason":"countdown continued while highlighted selection moved",
            "dry_run":dry_run,"hardware_verified":False}
    if not dry_run:file.write_text(text)
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mu",type=Path)
    parser.add_argument("--dry-run",action="store_true")
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    report=patch(args.mu,args.dry_run)
    print(json.dumps(report,indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+"\n")
if __name__=="__main__":main()

#!/usr/bin/env python3
"""Match four observed ARM64 EBS opcode words against a *specific* CI DxeCore.

The input words are the four 8-hex groups shown at Y308:
  live EBS address offsets +0, +4, +8, +0x70.
Do not assume that the current gBS->ExitBootServices pointer matches
CoreExitBootServices from the saved PE: first opcode A9BD53F3 was observed
while the pinned instrumented CoreExitBootServices begins A9BC53F3.
"""
from __future__ import annotations
import argparse
import bisect
import json
from pathlib import Path
import re

DIS = re.compile(r"^\s*([0-9a-fA-F]+):\s+([0-9a-fA-F]{8})\s", re.M)
SYMBOL = re.compile(r"^\s*([0-9a-fA-F]{8,16})\s+00000000\s+0\s+([\w$?.@]+)\s*$", re.M)
OFFSETS = (0, 4, 8, 0x70)

def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--disasm", type=Path, required=True)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--words", nargs=4, type=lambda x: int(x,16), required=True,
                    metavar=("PLUS0","PLUS4","PLUS8","PLUS70"))
    ap.add_argument("--ebs-pointer",type=lambda x:int(x,0))
    ap.add_argument("--pc",type=lambda x:int(x,0))
    args=ap.parse_args()
    if any(x<0 or x>0xffffffff for x in args.words):
        ap.error("expected four ARM64 32-bit instruction words, hex")
    instructions={int(a,16):int(b,16) for a,b in DIS.findall(args.disasm.read_text(errors="replace"))}
    sym=sorted((int(a,16),name) for a,name in SYMBOL.findall(args.map.read_text(errors="replace")))
    if not sym or not instructions:
        raise SystemExit("missing compiled DxeCore map symbols/disassembly")
    matches=[]
    for start, word in instructions.items():
        if word!=args.words[0]:
            continue
        n=sum(instructions.get(start+delta)==observed for delta,observed in zip(OFFSETS,args.words))
        idx=bisect.bisect_right(sym,(start,chr(0x10ffff)))-1
        symbol=sym[idx][1] if idx>=0 else None
        matches.append({"rva":hex(start),"symbol":symbol,
                        "from_symbol":hex(start-sym[idx][0]) if idx>=0 else None,
                        "matches":n, "exact_four_word_match":n==4})
    matches.sort(key=lambda t:(-t["matches"],int(t["rva"],16)))
    expected=[hex(a) for a,n in sym if n=="CoreExitBootServices"]
    print(json.dumps({
        "observed_words":[f"0x{x:08x}" for x in args.words],
        "offsets":[hex(x) for x in OFFSETS],
        "runtime_ebs_pointer":hex(args.ebs_pointer) if args.ebs_pointer is not None else None,
        "exception_pc":hex(args.pc) if args.pc is not None else None,
        "exception_delta":hex(args.pc-args.ebs_pointer)
            if args.ebs_pointer is not None and args.pc is not None else None,
        "compiled_core_exit_boot_services_rvas":expected,
        "first_opcode_matches_in_dxecore":len(matches),
        "exact_four_word_matches":sum(x["exact_four_word_match"] for x in matches),
        "best_matches":matches[:20],
        "limitation":"Static correlation only. A match does not prove runtime PE identity, "
            "relocation or successful EBS execution; no match suggests a different "
            "runtime code image, entry point or build."
    },indent=2))

if __name__=="__main__":
    main()

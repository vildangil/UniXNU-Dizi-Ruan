#!/usr/bin/env python3
"""Capture the exact disposable CI-built DXE Core symbols and PE binaries.

A firmware synchronous-exception PC is not a file offset. The companion
on-screen EBS function pointer supplies the runtime image anchor needed for
load-base-adjusted symbolization of CoreExitBootServices. Do not claim that a
static map alone resolves the live PC.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

REL = Path("Build/diziPkg/RELEASE_CLANGPDB/AARCH64/MdeModulePkg/Core/Dxe/DxeMain")

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mu", type=Path)
    ap.add_argument("dist", type=Path)
    args = ap.parse_args()
    mu = args.mu.resolve()
    dist = args.dist.resolve()
    source = mu / REL
    dest = dist / "dxe-core-symbols"
    dest.mkdir(parents=True, exist_ok=True)
    candidates = {
        "DxeCore.efi": [source / "OUTPUT/DxeCore.efi"],
        "DxeCore.dll": [source / "DEBUG/DxeCore.dll"],
        "DxeCore.map": [source / "DEBUG/DxeCore.map", source / "OUTPUT/DxeCore.map"],
        "DxeCore.pdb": [source / "DEBUG/DxeCore.pdb", source / "OUTPUT/DxeCore.pdb"],
    }
    entries = {}
    for name, paths in candidates.items():
        for path in paths:
            if path.is_file() and path.stat().st_size:
                destpath = dest / name
                shutil.copyfile(path, destpath)
                entries[name] = {
                    "sha256": hashlib.sha256(destpath.read_bytes()).hexdigest(),
                    "size": destpath.stat().st_size,
                    "from": str(path.relative_to(mu)),
                }
                break
    for name in ("DxeCore.efi", "DxeCore.dll"):
        if name not in entries:
            raise SystemExit(f"required DXE Core debug image missing: {name}")

    # Preserve PE headers and a disassembly even if lld-link's /lldmap
    # output has an unexpected filename (or symbols are optimized by LTO).
    for cmd, outfile in (
        (["llvm-readobj-18", "--file-headers", "--sections", str(dest/"DxeCore.efi")],
         "DxeCore.pe-headers.txt"),
        (["llvm-objdump-18", "-d", str(dest/"DxeCore.dll")],
         "DxeCore.disassembly.txt"),
    ):
        if not shutil.which(cmd[0]):
            cmd[0] = cmd[0].removesuffix("-18")
        if not shutil.which(cmd[0]):
            continue
        proc = subprocess.run(cmd, capture_output=True, text=True)
        (dest / outfile).write_text(proc.stdout if proc.returncode == 0
                                      else proc.stderr)
        if proc.returncode == 0:
            entries[outfile] = {
                "sha256": hashlib.sha256((dest/outfile).read_bytes()).hexdigest(),
                "size": (dest/outfile).stat().st_size,
            }
    report = {
        "source_revision": "mu_basecore bb557081f80f4883ed832e34ab36bdca6ede1e10",
        "known_exception_pc_candidates": ["0xFC368EAC", "0xFC369EAC"],
        "runtime_ebs_pointer": "read 16 hex digits at y=244 in on-device photo",
        "image_base_verified": False,
        "pc_symbolized": False,
        "no_xnu_entry": True,
        "files": entries,
    }
    (dist/"DXECORE-RESULT.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()

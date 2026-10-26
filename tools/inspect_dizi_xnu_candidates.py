#!/usr/bin/env python3
"""Inventory real experimental DIZI XNU kernel candidates in an artifact tree.

UniXNU and DarwinBoot are NOT kernels. Multiple boot-argument profiles for
one Mach-O do NOT count as multiple kernels. No files are patched/flashed.
Kernel validity is only a static format check, not an on-device boot result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect(path: Path, root: Path) -> dict:
    result = {"path": str(path.relative_to(root)), "size": path.stat().st_size,
              "is_arm64_macho": False, "hardware_boot_verified": False}
    if path.stat().st_size < 32:
        result["rejection"] = "shorter than Mach-O header"
        return result
    with path.open("rb") as fh:
        header = fh.read(32)
    magic, cpu, subtype, kind, cmds, cmdsize, flags, reserved = struct.unpack("<8I", header)
    result["magic"] = f"0x{magic:08x}"
    result["cpu_type"] = f"0x{cpu:08x}"
    result["subtype"] = subtype
    result["filetype"] = kind
    if not (magic == 0xFEEDFACF and cpu == 0x0100000C and kind == 2):
        result["rejection"] = "not AArch64 executable Mach-O"
        return result
    if cmds == 0 or cmdsize > path.stat().st_size - 32:
        result["rejection"] = "Mach-O load commands structurally invalid"
        return result
    result["is_arm64_macho"] = True
    result["sha256"] = sha256(path)
    result["load_command_count"] = cmds
    result["status"] = "candidate only; XNU hardware handoff unverified"
    return result


def inventory(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    found = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 300 * 1024 * 1024:
            continue
        # Only kernel-like filenames, not experimental Android boot containers.
        if not (re.search(r"(?:^kernel[.\-_]|^kernel$|\.macho$)", path.name, re.I)):
            continue
        found.append(inspect(path, directory))
    valid = [x for x in found if x["is_arm64_macho"]]
    distinct = len({x["sha256"] for x in valid})
    return {
        "real_kernel_candidates": valid,
        "excluded": [x for x in found if not x["is_arm64_macho"]],
        "distinct_kernel_macho_count": distinct,
        "boot_profiles": [
            {"name": "singlecpu", "source": "same stage1 kernel", "args": "-v keepsyms=1 debug=0x14e cpus=1"},
            {"name": "normal", "source": "same stage1 kernel", "args": "-v keepsyms=1 debug=0x14e"},
            {"name": "minimal", "source": "same stage1 kernel", "args": "-v cpus=1"}
        ],
        "haki_os_kernel_available": False,
        "uni_xnu_is_kernel": False,
        "hardware_verified": False,
        "missing_for_full_os": ["SM7435 drivers", "verified XNU entry", "root filesystem", "userland"],
    }


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("directory", type=Path)
    cli.add_argument("--report", type=Path)
    args = cli.parse_args()
    data = inventory(args.directory)
    result = json.dumps(data, indent=2) + "\n"
    print(result)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()

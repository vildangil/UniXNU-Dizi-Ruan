#!/usr/bin/env python3
"""Compile public patched XNU using the official UniXNU kernel machinery.

Use this from the *upstream UniXNU root* with a CI-only staged Dizi device.
This stops BEFORE binary prelink; no proprietary iPadOS kernelcache is used.
It does not make an XNU-bootable image or prove secondary CPUs work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    root = Path.cwd().resolve()
    device = args.device.resolve()
    sys.path.insert(0, str(root / "scripts"))
    from unixnu.cli import parser, prepare
    from unixnu.config import Context
    from unixnu import kernel

    if not (root / "unixnu").is_file():
        raise SystemExit("Run from the upstream UniXNU root")
    if args.jobs < 1 or args.jobs > 12:
        raise SystemExit("Invalid job limit")
    ctx = Context(parser().parse_args(
        ["build", "kernel", "-D", str(device), "-j", str(args.jobs)]
    ))
    ctx.refuse_example()
    config = ctx.need_config()
    if ctx.schema_version != 2 or ctx.name != "dizi":
        raise SystemExit("Expected staged Dizi format-2 profile")
    if ctx.board["board"]["soc_source"] != "sm7435":
        raise SystemExit("Wrong SoC source: refuse a foreign chipset")
    if ctx.board["board"]["os_profile"] != "ipados-17.7.11-21H461":
        raise SystemExit("Unexpected experimental build ABI profile")
    if ctx.board.get("kernel", {}).get("patch_series", []).count(
        "soc:patches/xnu/series"
    ) != 1:
        raise SystemExit("SM7435 SMP patch series not selected")
    if not config.get("XNU_ARMCPU") or not config.get("XNU_ARM_DT_PLATFORM"):
        raise SystemExit("ArmCpu/ArmDTPlatform not enabled")
    print("DIZI XNU SOURCE COMPILE: SM7435 + official XNU/UniXNU profiles")
    print("PRELINK DISABLED: no validated Dizi iPadOS kernelcache")
    print("This is a source compilation, not a boot image.", flush=True)

    modules = prepare(ctx, ["kernel"])
    # Upstream function: handles source XNU fetching, patches, archive
    # compilation and linker. We deliberately never call kernel.prelink().
    kernel.build(ctx, modules)
    raw = ctx.tree / ctx.board["kernel"]["prelink"]["kernel"]
    if not raw.is_file() or raw.stat().st_size < 1024:
        raise SystemExit(f"Missing raw XNU Mach-O: {raw}")
    data = raw.read_bytes()
    if len(data) < 32:
        raise SystemExit("Mach-O too small")
    magic, cpu, subtype, kind = struct.unpack_from("<4I", data)
    if (magic, cpu, kind) != (0xFEEDFACF, 0x0100000C, 2):
        raise SystemExit(
            f"Unexpected Mach-O header: {magic:x} {cpu:x} {kind:x}"
        )
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    target = out / "kernel.development.dizi-UNPRELINKED.macho"
    shutil.copyfile(raw, target)
    record = {
        "source": "official UniXNU patched Apple XNU",
        "device": "dizi",
        "soc": "SM7435",
        "upstream_os_profile": ctx.board["board"]["os_profile"],
        "kind": "unprelinked Mach-O source build",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "prelinked": False,
        "bootable": False,
        "hardware_tested": False,
        "remark": "No iPadOS kernelcache, ADT or DarwinBoot integration",
    }
    (out / "BUILD-RESULT.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"RAW_XNU_OK {target}: {record['bytes']} bytes, sha256 {record['sha256']}")


if __name__ == "__main__":
    main()

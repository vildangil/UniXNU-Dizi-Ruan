#!/usr/bin/env python3
"""Build a FAT RAM-disk with a DIZI XNU Mach-O + ADT for UniXNU.

Requires mtools (mformat, mmd, mcopy). Output is a filesystem image ONLY,
not an Android boot.img. The experiment never accesses device partitions.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from dizi_fat32 import build_fat32

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dizi-unixnu.toml"
MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
MH_EXECUTE = 2


def validate_kernel(path: Path) -> None:
    with path.open("rb") as stream:
        head = stream.read(32)
    if len(head) != 32:
        raise ValueError("kernel.macho is shorter than a Mach-O 64-bit header")
    magic, cpu, _subtype, ftype, ncmds, sizeofcmds, _flags, _reserved = struct.unpack(
        "<8I", head
    )
    if magic != MAGIC_64 or cpu != CPU_TYPE_ARM64 or ftype != MH_EXECUTE:
        raise ValueError("Expected an ARM64 MH_EXECUTE Mach-O (not SWEETXNU)")
    if not ncmds or sizeofcmds > path.stat().st_size - 32:
        raise ValueError("Invalid Mach-O load commands")


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def make_payload(kernel: Path, adt: Path, output: Path, size_mib: int = 128,
                 trustcache: Path | None = None) -> Path:
    kernel, adt, output = kernel.resolve(), adt.resolve(), output.resolve()
    validate_kernel(kernel)
    if not adt.is_file() or not (64 <= adt.stat().st_size <= 4 * 1024 * 1024):
        raise ValueError("ADT sidecar is missing or has an implausible size")
    if trustcache is not None and (not trustcache.is_file() or not trustcache.stat().st_size):
        raise ValueError("Trust-cache sidecar is missing or empty")
    if not (64 <= size_mib <= 512):
        raise ValueError("Expected a payload between 64 and 512 MiB")
    occupied = kernel.stat().st_size + adt.stat().st_size
    if trustcache:
        occupied += trustcache.stat().st_size
    if occupied + 16 * 1024 * 1024 >= size_mib * 1024 * 1024:
        raise ValueError("FAT volume has insufficient headroom for kernel data")
    if output.exists():
        raise FileExistsError(f"Will not overwrite an existing payload: {output}")
    if not CONFIG.is_file():
        raise FileNotFoundError(CONFIG)
    output.parent.mkdir(parents=True, exist_ok=True)
    contents = {
        "unixnu.toml": CONFIG,
        "kernel.macho": kernel,
        "kernel.macho.adt": adt,
    }
    if trustcache:
        contents["kernel.macho.trustcache"] = trustcache
    if all(shutil.which(name) for name in ("mformat", "mmd", "mcopy")):
        try:
            with output.open("xb") as stream:
                stream.truncate(size_mib * 1024 * 1024)
            run("mformat", "-i", str(output), "-F", "-v", "DIZIXNU", "::")
            for directory in ("::/EFI", "::/EFI/UniXNU", "::/EFI/UniXNU/Payloads"):
                run("mmd", "-i", str(output), directory)
            destinations = {
                "unixnu.toml": "::/EFI/UniXNU/unixnu.toml",
                "kernel.macho": "::/EFI/UniXNU/Payloads/kernel.macho",
                "kernel.macho.adt": "::/EFI/UniXNU/Payloads/kernel.macho.adt",
                "kernel.macho.trustcache": "::/EFI/UniXNU/Payloads/kernel.macho.trustcache",
            }
            for name, source in contents.items():
                run("mcopy", "-i", str(output), str(source), destinations[name])
        except FileExistsError:
            raise
        except Exception:
            output.unlink(missing_ok=True)
            raise
    else:
        build_fat32(output, size_mib * 1024 * 1024, contents)
    return output


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kernel", type=Path, required=True)
    ap.add_argument("--adt", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--size-mib", type=int, default=128)
    ap.add_argument("--trustcache", type=Path)
    args = ap.parse_args()
    print(make_payload(args.kernel, args.adt, args.output, args.size_mib,
                       args.trustcache))


if __name__ == "__main__":
    main()

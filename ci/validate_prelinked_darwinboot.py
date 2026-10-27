#!/usr/bin/env python3
"""Offline fail-closed DarwinBoot ParseKernel-compatible prelinked Mach-O check.

Not a runtime qualification: only the ELF/Mach-O shape, segment bounds, entry,
report provenance, and the 256 MiB UEFI window are tested. No XNU execution.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import struct
from pathlib import Path

WINDOW_SIZE = 256 << 20
BLOCK_SIZE = 2 << 20

def check(kernel: Path, report: Path, expected_source_run: int):
    details = json.loads(report.read_text())
    if details.get("source_run") != 40569002417:
        raise ValueError("XNU was not compiled from ABI-patched SM7435 run")
    if details.get("apple_ipados_build") != "21H461":
        raise ValueError("Unrecognized iPadOS prelink source")
    if details.get("apple_kernelcache_sha256") != "f18b4df865405f2a287b84977d7aca745e056d656d9fc9df1662970ce2969de7":
        raise ValueError("Original Apple kernelcache source mismatch")
    if any(details.get(key) is not False for key in
           ("bootable", "entry_allowed", "device_verified",
            "verified_ddr_map", "secondary_cpu_runtime")):
        raise ValueError("Experimental candidate incorrectly marked boot verified")
    if expected_source_run < 1:
        raise ValueError("Bad build run")

    image = kernel.read_bytes()
    sha = hashlib.sha256(image).hexdigest()
    if (sha != details["candidate_sha256"] or
            len(image) != details["candidate_size"] or
            not (35 << 20 < len(image) < 80 << 20)):
        raise ValueError("Candidate output does not match prelink report")

    if len(image) < 32:
        raise ValueError("Mach-O header missing")
    magic, cputype, subtype, filetype, count, commands, _flags, _ = struct.unpack_from("<8I", image)
    if (magic, cputype, subtype, filetype) != (0xfeedfacf, 0x100000c, 0, 2):
        raise ValueError("DarwinBoot refuses non-ARM64 executable")
    if commands > len(image) - 32 or not (1 <= count <= 128):
        raise ValueError("Invalid Mach-O commands")

    pos, end = 32, 32 + commands
    segments, entry = [], None
    for _ in range(count):
        if end - pos < 8:
            raise ValueError("Truncated load commands")
        cmd, size = struct.unpack_from("<II", image, pos)
        if size < 8 or size & 7 or size > end - pos:
            raise ValueError("Invalid load command")
        if cmd == 0x19:
            if size < 72:
                raise ValueError("Truncated LC_SEGMENT_64")
            name, va, memsz, off, filesz, _maxprot, initprot, sections, _flags = \
                struct.unpack_from("<16sQQQQIIII", image, pos + 8)
            if sections > (size - 72) // 80:
                raise ValueError("Invalid segment section count")
            if memsz:
                if (len(segments) >= 64 or memsz > WINDOW_SIZE or
                        va + memsz >= 1 << 64 or
                        filesz > memsz or off + filesz > len(image)):
                    raise ValueError("Invalid DarwinBoot kernel segment")
                segments.append((name.split(b"\0")[0].decode("ascii"), va, memsz, initprot))
        elif cmd == 5:
            if entry is not None or size != 288 or struct.unpack_from("<II", image, pos + 8) != (6, 68):
                raise ValueError("Malformed UnixThread")
            entry = struct.unpack_from("<Q", image, pos + 272)[0]
        pos += size
    if pos != end or entry is None or not segments:
        raise ValueError("Missing kernel entry or incomplete load commands")
    base = min(s[1] for s in segments)
    high = max(s[1] + s[2] for s in segments)
    if base & 4095 or high - base > WINDOW_SIZE - BLOCK_SIZE:
        raise ValueError("Kernel VA extent does not fit 256MiB window")
    if entry & 3 or not any(va <= entry < va + sz and (prot & 4) for _, va, sz, prot in segments):
        raise ValueError("Entry outside executable image")
    for i, (_name, va, sz, _) in enumerate(segments):
        if any(va < ov + os and ov < va + sz for _, ov, os, _ in segments[:i]):
            raise ValueError("Overlapping segments")

    out = {
        "source_run": details["source_run"],
        "prelink_run": expected_source_run,
        "sha256": sha,
        "file_bytes": len(image),
        "segment_count": len(segments),
        "virtual_base": hex(base),
        "virtual_end": hex(high),
        "virtual_span": hex(high - base),
        "entry_va": hex(entry),
        "kernel_abi_candidate": "prelinked SM7435/iPadOS 17.7.11",
        "loader_shape_accepted": True,
        "memory_allocated_on_device": False,
        "kernel_entry_executed": False,
        "is_bootable": False,
    }
    print(json.dumps(out, indent=2))
    return out

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--kernel", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--source-run", type=int, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = check(args.kernel, args.report, args.source_run)
    args.output.write_text(json.dumps(result, indent=2) + "\n")

#!/usr/bin/env python3
"""Construct a pinned XNU+Apple iPadOS 17.7.11 PRELINK CANDIDATE, host-side.

This program refuses to claim that the candidate is bootable and never builds
a boot.img.  It reads only KernelCache from an official Apple IPSW using HTTP
Range ZIP access, validates the Apple original against UniXNU's SHA-256 pin,
and calls UniXNU's own emit_prelink.py at its gitlink revision.
Apple's original code is not checked into the device repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import shutil
import struct
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path


def digest(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def native_check(path: Path):
    if not path.is_file() or not 1_000_000 < path.stat().st_size < 100_000_000:
        raise ValueError("Missing or implausible built native Mach-O")
    h = digest(path)
    if h != "bb0f258f3ccb08538b541f6d3165a23bfbf3c4a4ffbb3ab9d26f1e1efb916923":
        raise ValueError(f"Native XNU digest differs from host-compiled run #40552223877: {h}")
    with path.open("rb") as stream:
        header = stream.read(16)
    if struct.unpack("<4I", header)[:2] != (0xfeedfacf, 0x0100000c):
        raise ValueError("Native kernel is not ARM64 Mach-O")


def extract_original(upstream: Path, os_profile: dict, output: Path):
    # Import the official IPSW ZIP-range and IM4P parsers, not third-party
    # Apple-file mirrors or a separately written unverified IM4P decoder.
    sys.path.insert(0, str(upstream / "scripts"))
    from unixnu.ipsw import RangeFile, im4p_payload

    ipsw = os_profile["ipsw"]
    prelink = os_profile["kernel"]["prelink"]
    if (ipsw["version"], ipsw["build"], ipsw["product"], ipsw["device_class"]) != (
        "17.7.11", "21H461", "iPad7,1", "j120ap"
    ):
        raise ValueError("Unexpected Apple IPSW profile or device class")
    if ipsw["url"].split("/")[2] != "updates.cdn-apple.com":
        raise ValueError("Official Apple IPSW host required")
    print("Reading Apple IPSW directory over HTTPS range (no full 6.4 GiB download)", flush=True)
    reader = RangeFile(ipsw["url"])
    with zipfile.ZipFile(reader) as archive:
        m = plistlib.loads(archive.read("BuildManifest.plist"))
        if (m["ProductVersion"], m["ProductBuildVersion"]) != (ipsw["version"], ipsw["build"]):
            raise ValueError("Apple BuildManifest release/build mismatch")
        if ipsw["product"] not in m["SupportedProductTypes"]:
            raise ValueError("Apple BuildManifest excludes selected device")
        ids = [
            v for v in m["BuildIdentities"]
            if v["Info"]["DeviceClass"] == ipsw["device_class"]
            and v["Info"]["RestoreBehavior"] == "Erase"
            and int(v["ApChipID"], 16) == ipsw["chip_id"]
            and int(v["ApBoardID"], 16) == ipsw["board_id"]
        ]
        if len(ids) != 1:
            raise ValueError(f"Expected one pinned Apple erase identity; found {len(ids)}")
        member = ids[0]["Manifest"]["KernelCache"]["Info"]["Path"]
        stat = archive.getinfo(member)
        if not 0 < stat.file_size < 250_000_000:
            raise ValueError("Unexpected kernelcache member size")
        print(f"IPSW identity matched; reading KernelCache member {member} ({stat.file_size} B)", flush=True)
        im4p = archive.read(member)
    packed_bytes = im4p_payload(im4p)
    if not 0 < len(packed_bytes) < 250_000_000:
        raise ValueError("Bad IM4P payload size")
    pack = output / "apple-kernelcache.lzfse"
    fat = output / "apple-kernelcache.fat"
    pack.write_bytes(packed_bytes)
    decoder = Path("/usr/bin/compression_tool")
    if not decoder.is_file():
        raise RuntimeError("macOS native compression_tool unavailable")
    subprocess.run([str(decoder), "-decode", "-a", "lzfse",
                    "-i", str(pack), "-o", str(fat)], check=True)
    data = fat.read_bytes()
    if data[:4] == b"\xca\xfe\xba\xbe":
        ns = struct.unpack_from(">I", data, 4)[0]
        slices = [
            struct.unpack_from(">5I", data, 8 + 20 * i) for i in range(ns)
        ]
        arm = [t for t in slices if t[0] == 0x0100000c]
        if len(arm) != 1:
            raise ValueError("Expected exactly one arm64 cache slice")
        _cpu, _sub, off, size, _align = arm[0]
        data = data[off:off + size]
    if data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Extracted original is not ARM64 Mach-O")
    original = output / "apple-kernelcache.decompressed"
    original.write_bytes(data)
    raw_hash = digest(original)
    if raw_hash != prelink["kernelcache_sha256"]:
        raise ValueError(f"IPSW kernelcache failed official pin: {raw_hash}")
    pack.unlink()
    fat.unlink()
    print("Official Apple kernelcache matches upstream UniXNU pin", raw_hash, flush=True)
    return original


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--upstream", type=Path, required=True)
    p.add_argument("--native", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    upstream, native, output = (x.resolve() for x in (args.upstream, args.native, args.output))
    os_file = upstream / "profiles/os/ipados-17.7.11-21H461/profile.toml"
    os_profile = tomllib.loads(os_file.read_text())
    prelink = os_profile["kernel"]["prelink"]
    script = upstream / prelink["tool"]
    if not script.is_file() or not (script.parent / "native_prelink.py").is_file():
        raise FileNotFoundError("Missing pinned upstream XnuPrelink git submodule")
    if prelink["slide"] != "-0x1000000":
        raise ValueError("Unexpected slide; do not silently change ABI")
    native_check(native)
    output.mkdir(parents=True, exist_ok=True)
    scratch = output / "private-work"
    scratch.mkdir(exist_ok=True)
    original = extract_original(upstream, os_profile, scratch)
    candidate = output / "kernel.prelinked.dizi-CANDIDATE.macho"
    command = [sys.executable, str(script), "--kernel", str(native),
               "--prelinked", str(original), "--slide=" + prelink["slide"],
               "--output", str(candidate)]
    for root in prelink["roots"]:
        command.extend(["--root", root])
    security = prelink.get("early_security_init", [])
    # Upstream profile.toml may encode this as one TOML string rather than
    # a list. Iterating a string produced one command argument per character.
    if isinstance(security, str):
        security = [security] if security else []
    if not isinstance(security, list) or any(
        not isinstance(item, str) or item.count("=") != 1 for item in security
    ):
        raise ValueError("Unexpected early_security_init value in OS profile")
    for item in security:
        command.extend(["--early-security-init", item])
    print(f"Prelink {len(prelink['roots'])} original Apple components to native XNU", flush=True)
    subprocess.run(command, check=True, cwd=upstream)
    if candidate.stat().st_size < native.stat().st_size:
        raise ValueError("Prelink did not produce expected candidate image")
    with candidate.open("rb") as f:
        if struct.unpack("<4I", f.read(16))[:2] != (0xfeedfacf, 0x0100000c):
            raise ValueError("Prelink output not an ARM64 Mach-O")
    report = {
        "source_run": 40552223877,
        "native_sha256": digest(native),
        "candidate_sha256": digest(candidate),
        "candidate_size": candidate.stat().st_size,
        "apple_kernelcache_sha256": prelink["kernelcache_sha256"],
        "apple_ipados_version": os_profile["ipsw"]["version"],
        "apple_ipados_build": os_profile["ipsw"]["build"],
        "product_abi_candidate": "iPad7,1 / J120AP; not validated on Qualcomm SM7435",
        "original_apple_component_roots": len(prelink["roots"]),
        "bootable": False,
        "device_verified": False,
        "entry_allowed": False,
        "verified_ddr_map": False,
        "verified_adt_identity": False,
        "secondary_cpu_runtime": False,
        "stage": "host-side prelink candidate only; no EDK2 ExitBootServices",
    }
    (output / "PRELINK-RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    print("PRELINK CANDIDATE BUILT (NOT BOOT VERIFIED)", candidate.stat().st_size, flush=True)
    # The Apple original kernelcache is not copied to release artifacts.
    shutil.rmtree(scratch)


if __name__ == "__main__":
    main()

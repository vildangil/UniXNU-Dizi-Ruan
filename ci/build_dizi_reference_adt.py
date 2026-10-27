#!/usr/bin/env python3
"""Generate and validate a Dizi ADT reference, NOT a boot-safe memory map.

Intended for fail-closed DarwinBoot parsing experiment only. The contiguous
3 GiB high RAM bank is observed in a boot FDT but its runtime reservations
and EFI/XNU ownership are NOT validated. Never boot XNU using this ADT.
"""
from __future__ import annotations
import argparse
import json
import struct
import subprocess
import sys
import tomllib
from pathlib import Path


def parse_adt(blob: bytes):
    """Small bounded reader for Apple ADT's packed LE property/child format."""
    view = memoryview(blob)
    cursor = 0
    def child(depth=0):
        nonlocal cursor
        if depth > 16 or cursor + 8 > len(blob):
            raise ValueError("ADT truncated or too deep")
        nprops, nchildren = struct.unpack_from("<II", view, cursor)
        cursor += 8
        if nprops > 100 or nchildren > 100:
            raise ValueError("Unbounded ADT child/property count")
        props = {}
        for _ in range(nprops):
            if cursor + 36 > len(blob):
                raise ValueError("ADT truncated property")
            raw, size = struct.unpack_from("<32sI", view, cursor)
            cursor += 36
            if size > 2_000_000 or size > len(blob) - cursor:
                raise ValueError("ADT invalid value size")
            key = raw.partition(b"\0")[0].decode("ascii")
            if key in props:
                raise ValueError("ADT duplicate property")
            props[key] = bytes(view[cursor:cursor + size])
            cursor += (size + 3) & ~3
            if cursor > len(blob):
                raise ValueError("ADT alignment overflow")
        name = props.get("name", b"").rstrip(b"\0").decode("ascii")
        children = [child(depth + 1) for _ in range(nchildren)]
        return {"name": name, "props": props, "children": children}
    root = child()
    if cursor != len(blob):
        raise ValueError("ADT has trailing bytes")
    return root


def find(root, *names):
    for name in names:
        root = next((c for c in root["children"] if c["name"] == name), None)
        if root is None:
            raise ValueError("ADT node missing: " + "/".join(names))
    return root


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device", required=True, type=Path)
    p.add_argument("--soc", required=True, type=Path)
    p.add_argument("--unixnu", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    device, soc, unixnu, output = (x.resolve() for x in (a.device, a.soc, a.unixnu, a.output))
    hardware = json.loads((device / "data/dizi-fdt-observed.json").read_text())
    assert hardware["device"] == "dizi" and hardware["soc"] == "SM7435"
    assert hardware["ram_candidate"]["validated_on_device"] is False
    bank = hardware["memory_banks"][-1]
    assert (bank["base"], bank["size"]) == (0x8C0000000, 0xC0000000)
    source = (device / "dts/dizi.dts").read_text()
    assert source.endswith("};\n") and "memory@" not in source
    temp = output / "working"
    temp.mkdir(parents=True, exist_ok=True)
    low = bank["base"] & 0xffffffff
    high = bank["base"] >> 32
    size_low = bank["size"] & 0xffffffff
    size_high = bank["size"] >> 32
    addition = (
        "    // CI-only unverified DRAM bank from observed FDT.\n"
        "    // DO NOT use for actual XNU memory ownership or ExitBootServices.\n"
        "    memory@%x {\n"
        '        device_type = "memory";\n'
        "        reg = <0x%x 0x%x 0x%x 0x%x>;\n"
        "    };\n"
    ) % (bank["base"], high, low, size_high, size_low)
    staged = temp / "dizi-reference-only.dts"
    staged.write_text(source[:-3] + addition + "};\n")
    dtb = temp / "dizi-reference-only.dtb"
    subprocess.run(["dtc", "-I", "dts", "-O", "dtb", "-i",
                    str(soc / "dts"), "-o", str(dtb), str(staged)], check=True)
    sys.path.insert(0, str(unixnu / "scripts"))
    from unixnu.devicetree import generate
    from unixnu.profiles import merge
    os_profile = unixnu / "profiles/os/ipados-17.7.11-21H461/profile.toml"
    config = merge(tomllib.loads(os_profile.read_text()),
                   tomllib.loads((device / "board.toml").read_text()))
    blob = generate(dtb, config, unique_chip_id=None, data=False, trust=False, addon=False)
    root = parse_adt(blob)
    assert root["name"] == "device-tree"
    chosen = find(root, "chosen")["props"]
    assert struct.unpack("<Q", chosen["dram-base"])[0] == bank["base"]
    assert struct.unpack("<Q", chosen["dram-size"])[0] == bank["size"]
    cpus = find(root, "cpus")["children"]
    assert len(cpus) == 8
    assert [struct.unpack("<I", c["props"]["reg"])[0] for c in cpus] == [i << 8 for i in range(8)]
    assert [chr(struct.unpack("<I", c["props"]["cluster-type"])[0]) for c in cpus] == list("EEEEPPPP")
    assert find(root, "psci")["props"]["method"] == b"smc\0"
    intc = find(root, "arm-io", "intc")["props"]
    assert intc["compatible"] == b"arm,gic-v3\0"
    assert struct.unpack("<Q", intc["redistributor-stride"])[0] == 0x20000
    assert len(intc["reg"]) == 32
    output.mkdir(parents=True, exist_ok=True)
    filename = output / "kernel.macho.adt"
    filename.write_bytes(blob)
    report = {
        "purpose": "DarwinBoot ADT parsing test only, NOT for XNU execution",
        "source": "Observed Dizi FDT + pinned SM7435 DTSI + upstream UniXNU ADT generator",
        "target": "SM7435/dizi",
        "cpus": 8,
        "clusters": "EEEEPPPP",
        "psci": "smc",
        "gic_distributor": hex(hardware["gic"]["distributor"]),
        "gic_redistributor": hex(hardware["gic"]["redistributor"]),
        "gic_rstride": "0x20000",
        "adt_bytes": len(blob),
        "observed_memory_base": hex(bank["base"]),
        "observed_memory_size": hex(bank["size"]),
        "memory_ownership_verified": False,
        "kernel_prelinked": False,
        "kernel_entry_authorized": False,
    }
    (output / "ADT-REFERENCE-RESULT.json").write_text(json.dumps(report, indent=2) + "\n")
    print("DIZI REFERENCE ADT GENERATED:", filename, len(blob), "bytes")
    print("DIZI ADT HAS 8 MPIDRs, PSCI, GICv3; MEMORY IS UNVERIFIED")
    print("CRITICAL: fail-closed loader; no actual XNU handoff permitted")


if __name__ == "__main__":
    main()

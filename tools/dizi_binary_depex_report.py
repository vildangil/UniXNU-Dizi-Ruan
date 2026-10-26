#!/usr/bin/env python3
"""Read actual Qualcomm binary DXE_DEPEX expressions, not their INF text.

Only reads .depex files and .dec GUID declarations from a checked-out Mu repo.
Never executes EFI binaries, writes MMIO, or changes firmware.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import uuid

OPS = {
    0x00: "BEFORE", 0x01: "AFTER", 0x02: "PUSH",
    0x03: "AND", 0x04: "OR", 0x05: "NOT",
    0x06: "TRUE", 0x07: "FALSE", 0x08: "END", 0x09: "SOR"
}
TARGETS = {
    "ButtonsDxe": "ButtonsDxe/ButtonsDxe.depex",
    "XhciPciEmulationDxe": "XhciPciEmulationDxe/XhciPciEmulationDxe.depex",
    "UsbInitDxe": "UsbInitDxe/UsbInitDxe.depex",
    "UsbConfigDxe": "UsbConfigDxe/UsbConfigDxe.depex",
    "GpiDxe": "GpiDxe/GpiDxe.depex",
    "PmicGlinkDxe": "PmicGlinkDxe/PmicGlinkDxe.depex",
}


def guid_names(root):
    names = {}
    # A Qualcomm protocol GUID can be declared in a DEC outside QcomPkg.
    for p in root.rglob("*.dec"):
        try:
            source = p.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for line in source.splitlines():
            if "=" not in line or "{" not in line:
                continue
            label, expr = line.split("=", 1)
            label = label.strip()
            if not re.fullmatch(r"g[A-Za-z0-9_]+", label):
                continue
            expr = expr.split("#", 1)[0]
            nums = re.findall(r"0[xX][0-9a-fA-F]+", expr)
            if len(nums) != 11:
                continue
            try:
                fields = [int(n, 16) for n in nums]
                raw = struct.pack("<IHH8B", *fields)
                identifier = str(uuid.UUID(bytes_le=raw))
                names.setdefault(identifier, []).append(label)
            except (ValueError, struct.error):
                pass
    return {k: sorted(set(v)) for k, v in names.items()}


def decode_depex(data, names=None):
    names = names or {}
    stack = []
    tokens = []
    guid_set = []
    pos = 0
    result = None
    before_after = None
    saw_end = False
    while pos < len(data):
        op = data[pos]
        pos += 1
        if op not in OPS:
            raise ValueError("invalid DEPEX opcode at byte %d: 0x%02x" % (pos - 1, op))
        mnemonic = OPS[op]
        tokens.append(mnemonic)
        if op in (0x00, 0x01, 0x02):
            if pos + 16 > len(data):
                raise ValueError("truncated DEPEX protocol GUID")
            ident = str(uuid.UUID(bytes_le=data[pos:pos+16]))
            pos += 16
            guid_set.append(ident)
            label = ",".join(names.get(ident, [])) or ident
            if op == 0x02:
                stack.append(label)
            else:
                if len(data) - pos < 1 or data[pos] != 0x08:
                    raise ValueError("BEFORE/AFTER must end immediately")
                before_after = mnemonic + "(" + label + ")"
        elif op == 0x06:
            stack.append("TRUE")
        elif op == 0x07:
            stack.append("FALSE")
        elif op == 0x05:
            if len(stack) < 1:
                raise ValueError("NOT stack underflow")
            stack.append("(NOT " + stack.pop() + ")")
        elif op in (0x03, 0x04):
            if len(stack) < 2:
                raise ValueError(mnemonic + " stack underflow")
            right, left = stack.pop(), stack.pop()
            stack.append("(" + left + " " + mnemonic + " " + right + ")")
        elif op == 0x09:
            if pos != 1:
                raise ValueError("SOR must be the first opcode")
        elif op == 0x08:
            if before_after:
                result = before_after
            elif len(stack) == 1:
                result = stack[0]
            else:
                raise ValueError("invalid DEPEX final stack size " + str(len(stack)))
            if pos != len(data):
                raise ValueError("unexpected bytes after DEPEX END")
            saw_end = True
            break
    if not saw_end:
        raise ValueError("missing DEPEX END opcode")
    return {
        "raw_bytes": len(data), "expression": result,
        "guid_dependencies": [
            {"guid": x, "symbols": names.get(x, [])}
            for x in sorted(set(guid_set))
        ],
        "opcodes": tokens,
        "parsed": True,
    }


def inspect(root):
    base = root / "Binaries/dizi/QcomPkg/Drivers"
    if not base.is_dir():
        raise FileNotFoundError("DIZI binary submodule checkout missing")
    symbols = guid_names(root)
    reports = {}
    for name, relative in TARGETS.items():
        path = base / relative
        if not path.is_file():
            reports[name] = {"status": "no binary .depex file", "path": relative}
            continue
        reports[name] = {"status": "parsed", "path": relative,
                         **decode_depex(path.read_bytes(), symbols)}
    return {
        "scope": "offline actual binary DEPEX only, not physical hardware",
        "source": "pinned DIZI external Qualcomm firmware submodule",
        "dependencies": reports,
        "buttons_physical_events_verified": False,
        "usb_host_initialized": False,
        "note": "TRUE in .inf is not proof that the actual .depex is TRUE."
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mu_checkout", type=Path)
    p.add_argument("--json-out", type=Path)
    args = p.parse_args()
    data = inspect(args.mu_checkout)
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text)


if __name__ == "__main__":
    main()

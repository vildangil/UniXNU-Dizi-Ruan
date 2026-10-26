"""Minimal FAT32/VFAT disk-image writer for the DIZI read-only RAM payload.

Pure Python standard library: the Arch runner does not require mtools.
This deliberately supports a small, fixed directory tree only. No block
devices, partitions, mounting, root privileges or existing file overwrites.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

BPS = 512
SPC = 1                 # 512-byte clusters: >= 64 MiB remains FAT32
RESERVED = 32
NFATS = 2
EOC = 0x0FFFFFFF


def _short_entry(alias: str, attr: int, cluster: int, size: int = 0) -> bytes:
    if alias in (".", ".."):
        base, ext = alias, ""
    else:
        base, ext = (alias.split(".", 1) + [""])[:2] if "." in alias else (alias, "")
        if not (1 <= len(base) <= 8 and len(ext) <= 3):
            raise ValueError(f"Invalid 8.3 alias {alias}")
    raw = bytearray(32)
    raw[:11] = (base.ljust(8) + ext.ljust(3)).encode("ascii")
    raw[11] = attr
    struct.pack_into("<H", raw, 20, cluster >> 16)
    struct.pack_into("<H", raw, 26, cluster & 0xFFFF)
    struct.pack_into("<I", raw, 28, size)
    return bytes(raw)


def _checksum(shortname: bytes) -> int:
    result = 0
    for ch in shortname:
        result = (((result & 1) << 7) | (result >> 1)) + ch
        result &= 0xFF
    return result


def _vfat_entries(name: str, short: bytes) -> list[bytes]:
    units = [int.from_bytes(name.encode("utf-16le")[i:i+2], "little")
             for i in range(0, len(name.encode("utf-16le")), 2)]
    units.append(0)
    groups = [units[i:i+13] for i in range(0, len(units), 13)]
    check = _checksum(short[:11])
    out = []
    for i in range(len(groups), 0, -1):
        chars = groups[i-1] + [0xFFFF] * (13 - len(groups[i-1]))
        slot = bytearray(32)
        slot[0] = i | (0x40 if i == len(groups) else 0)
        slot[11] = 0x0F
        slot[12] = 0
        slot[13] = check
        struct.pack_into("<H", slot, 26, 0)
        for index, offset in enumerate((1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30)):
            struct.pack_into("<H", slot, offset, chars[index])
        out.append(bytes(slot))
    return out


def _record(name: str, alias: str, attr: int, cluster: int, size: int = 0) -> bytes:
    short = _short_entry(alias, attr, cluster, size)
    return b"".join(_vfat_entries(name, short)) + short


def _geometry(size: int) -> tuple[int, int, int]:
    if size % BPS:
        raise ValueError("FAT size must be a multiple of 512")
    sectors = size // BPS
    # Use an upper bound. A naive fixed-point iteration can oscillate
    # between two FAT sizes for a 64 MiB image.
    fat_sectors = math.ceil((sectors - RESERVED + 2) * 4 / (BPS * SPC + NFATS * 4))
    while True:
        clusters = (sectors - RESERVED - NFATS * fat_sectors) // SPC
        needed = math.ceil((clusters + 2) * 4 / BPS)
        if needed <= fat_sectors:
            break
        fat_sectors = needed
    if not 65525 <= clusters < 0x0FFFFFF5:
        raise ValueError("Volume outside FAT32 cluster-count range")
    return sectors, fat_sectors, clusters


def build_fat32(path: Path, size: int, files: dict[str, Path]) -> None:
    """Make EFI/UniXNU/{unixnu.toml,Payloads/*} in a new FAT32 image."""
    if path.exists():
        raise FileExistsError(path)
    sectors, fat_sectors, clusters = _geometry(size)
    data_lba = RESERVED + NFATS * fat_sectors
    next_cluster = 6    # root=2, EFI=3, UniXNU=4, Payloads=5
    chain: dict[str, tuple[int, int, int]] = {}
    table = bytearray(fat_sectors * BPS)

    def set_fat(c: int, value: int) -> None:
        struct.pack_into("<I", table, c * 4, value)

    set_fat(0, 0x0FFFFFF8)
    set_fat(1, 0xFFFFFFFF)
    for c in (2, 3, 4, 5):
        set_fat(c, EOC)

    expected = {"unixnu.toml", "kernel.macho", "kernel.macho.adt"}
    if not expected.issubset(files):
        raise ValueError(f"Required payload files absent: {expected - files.keys()}")
    allowed = expected | {"kernel.macho.trustcache"}
    if set(files) - allowed:
        raise ValueError("Unexpected payload file")
    for name, source in files.items():
        source = Path(source)
        length = source.stat().st_size
        if length == 0 or length >= 0x100000000:
            raise ValueError(f"Invalid file length for {name}")
        n = math.ceil(length / BPS)
        if next_cluster + n > clusters + 2:
            raise ValueError("Not enough FAT clusters")
        first = next_cluster
        for c in range(first, first + n):
            set_fat(c, EOC if c + 1 == first + n else c + 1)
        chain[name] = (first, n, length)
        next_cluster += n

    def directory(entries: list[bytes]) -> bytes:
        payload = b"".join(entries)
        if len(payload) > BPS - 32:
            raise ValueError("FAT directory exceeds one cluster")
        return payload.ljust(BPS, b"\0")

    root = directory([_record("EFI", "EFI", 0x10, 3)])
    efi = directory([_short_entry(".", 0x10, 3),
                     _short_entry("..", 0x10, 2),
                     _record("UniXNU", "UNIXNU", 0x10, 4)])
    ux = directory([_short_entry(".", 0x10, 4),
                    _short_entry("..", 0x10, 3),
                    _record("Payloads", "PAYLOADS", 0x10, 5),
                    _record("unixnu.toml", "UNIXNU~1.TOM", 0x20,
                            chain["unixnu.toml"][0], chain["unixnu.toml"][2])])
    payload_aliases = {
        "kernel.macho": "KERNEL~1.MAC",
        "kernel.macho.adt": "KERNEL~2.ADT",
        "kernel.macho.trustcache": "KERNEL~3.TRU",
    }
    payload_entries = [_short_entry(".", 0x10, 5), _short_entry("..", 0x10, 4)]
    for name in ("kernel.macho", "kernel.macho.adt", "kernel.macho.trustcache"):
        if name in chain:
            payload_entries.append(_record(name, payload_aliases[name], 0x20,
                                           chain[name][0], chain[name][2]))
    payload_dir = directory(payload_entries)

    boot = bytearray(BPS)
    boot[:11] = b"\xEB\x58\x90DIZIXNU "
    struct.pack_into("<HBHBHHBHHHII", boot, 11,
                     BPS, SPC, RESERVED, NFATS, 0, 0, 0xF8, 0, 63, 255, 0, sectors)
    struct.pack_into("<IHHIHH", boot, 36, fat_sectors, 0, 0, 2, 1, 6)
    boot[64] = 0x80
    boot[66] = 0x29
    struct.pack_into("<I", boot, 67, 0xD1211026)
    boot[71:82] = b"DIZI UNIXNU"
    boot[82:90] = b"FAT32   "
    boot[510:512] = b"\x55\xAA"

    fsinfo = bytearray(BPS)
    struct.pack_into("<I", fsinfo, 0, 0x41615252)
    struct.pack_into("<I", fsinfo, 484, 0x61417272)
    struct.pack_into("<II", fsinfo, 488, 0xFFFFFFFF, 0xFFFFFFFF)
    struct.pack_into("<I", fsinfo, 508, 0xAA550000)

    # Open exclusive and only ever write the new file, never an external device.
    try:
        with path.open("xb") as out:
            out.truncate(size)
            out.seek(0)
            out.write(boot)
            out.write(fsinfo)
            out.seek(6 * BPS)
            out.write(boot)
            out.write(fsinfo)
            out.seek(RESERVED * BPS)
            out.write(table)
            out.write(table)
            for c, data in ((2, root), (3, efi), (4, ux), (5, payload_dir)):
                out.seek((data_lba + (c - 2) * SPC) * BPS)
                out.write(data)
            for name, source in files.items():
                first, _n, _length = chain[name]
                out.seek((data_lba + (first - 2) * SPC) * BPS)
                with Path(source).open("rb") as inp:
                    while True:
                        chunk = inp.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
    except FileExistsError:
        # Another process may have created the file after the initial check.
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise

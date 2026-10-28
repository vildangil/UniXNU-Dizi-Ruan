#!/usr/bin/env python3
"""Repackage the fourth NO-SP checkpoint WITHOUT rebuilding working EDK2.

Input is the exact SHA-pinned, hardware-confirmed third-NOSP Android boot-v4
image. Read the kernel.macho file through its FAT32 cluster chain, patch a
COPY with ci/patch_dizi_fourth_mmu_stackless.py, and write back ONLY the
78 changed file bytes. Preserve firmware, FAT headers, filenames, other
payloads, and every unrelated byte. Fail closed on ANY SHA/layout mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

SOURCE_BOOT_SHA = "05d64e67f2a78af69c5be66e43fb07ae8495d65a452083daad70fa8bc878a890"
OUTPUT_BOOT_SHA = "16e05fc877d7adc04c17fea1372ba2e9ed218f47a7f485875290879619e50c72"
SOURCE_MACHO_SHA = "37ecddf974a59a8c3a74527bdd09914a6c2f67f49d71af7b00c45bc5051d3ff2"
OUTPUT_MACHO_SHA = "b1ec254a0038208cad8ce4284ff759a33b096436208505cafc3e084be4361fa3"
BOOT_LENGTH = 68800512
FAT_OFFSET = 0x19C000
FAT_LENGTH = 64 * 1024 * 1024
MACHO_LENGTH = 51941376

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def main(src: Path, dest: Path, report: Path) -> None:
    if src.resolve() == dest.resolve():
        raise ValueError("Refusing in-place boot.img overwrite")
    boot = bytearray(src.read_bytes())
    if (len(boot) != BOOT_LENGTH or sha(boot) != SOURCE_BOOT_SHA or
            boot[:8] != b"ANDROID!" or struct.unpack_from("<I", boot, 40)[0] != 4):
        raise ValueError("Refusing unpinned Android boot-v4 source image")
    fat = memoryview(boot)[FAT_OFFSET:FAT_OFFSET + FAT_LENGTH]
    if len(fat) != FAT_LENGTH or fat[82:87].tobytes() != b"FAT32":
        raise ValueError("FAT32 source absent")
    bps = struct.unpack_from("<H", fat, 11)[0]
    spc = fat[13]
    res = struct.unpack_from("<H", fat, 14)[0]
    nfats = fat[16]
    sectors_per_fat = struct.unpack_from("<I", fat, 36)[0]
    root = struct.unpack_from("<I", fat, 44)[0]
    if (bps, spc, res, nfats, sectors_per_fat, root) != (512, 1, 32, 2, 1009, 2):
        raise ValueError("Pinned FAT32 geometry changed")
    fat_table = res * bps
    cluster_len = bps * spc
    cluster_start = (res + nfats * sectors_per_fat) * bps

    def next_cluster(cluster: int) -> int:
        return struct.unpack_from("<I", fat, fat_table + cluster * 4)[0] & 0x0FFFFFFF

    def chain(first: int):
        seen = set()
        while 2 <= first < 0x0FFFFFF8:
            if first in seen or len(seen) > 130000:
                raise ValueError("Corrupt FAT32 cluster chain")
            seen.add(first)
            yield first
            first = next_cluster(first)

    def cluster_pos(cluster: int) -> int:
        off = cluster_start + (cluster - 2) * cluster_len
        if off < 0 or off + cluster_len > len(fat):
            raise ValueError("Cluster escapes FAT32")
        return off

    def entries(first: int):
        for cl in chain(first):
            off = cluster_pos(cl)
            for i in range(0, cluster_len, 32):
                item = fat[off + i:off + i + 32]
                if item[0] == 0:
                    return
                if item[0] == 0xE5 or item[11] == 0x0F:
                    continue
                name = bytes(item[:8]).decode("ascii").strip()
                ext = bytes(item[8:11]).decode("ascii").strip()
                if ext:
                    name += "." + ext
                first_cluster = (
                    struct.unpack_from("<H", item, 20)[0] << 16
                ) | struct.unpack_from("<H", item, 26)[0]
                size = struct.unpack_from("<I", item, 28)[0]
                yield name, item[11], first_cluster, size

    def find_dir(parent: int, component: str) -> int:
        matches = [e for e in entries(parent) if e[0].lower() == component.lower()]
        if len(matches) != 1 or not (matches[0][1] & 0x10):
            raise ValueError("FAT32 directory missing: " + component)
        return matches[0][2]

    payload_dir = find_dir(find_dir(find_dir(root, "EFI"), "UNIXNU"), "PAYLOADS")
    candidates = [e for e in entries(payload_dir) if e[0] == "KERNEL~1.MAC" and e[3] == MACHO_LENGTH]
    if len(candidates) != 1 or candidates[0][1] & 0x10:
        raise ValueError("Expected kernel.macho FAT32 entry not found")
    clusters = list(chain(candidates[0][2]))
    if len(clusters) != (MACHO_LENGTH + cluster_len - 1) // cluster_len:
        raise ValueError("Kernel FAT32 chain length mismatch")
    original_kernel = b"".join(
        bytes(fat[cluster_pos(cl):cluster_pos(cl) + cluster_len]) for cl in clusters
    )[:MACHO_LENGTH]
    if sha(original_kernel) != SOURCE_MACHO_SHA:
        raise ValueError("FAT32 Mach-O SHA does not match pinned source")

    with tempfile.TemporaryDirectory(prefix="dizi-fourth-") as tmp:
        d = Path(tmp)
        input_macho = d / "input.macho"
        output_macho = d / "output.macho"
        kernel_report = d / "kernel-report.json"
        input_macho.write_bytes(original_kernel)
        subprocess.run([
            sys.executable, str(Path(__file__).with_name("patch_dizi_fourth_mmu_stackless.py")),
            "--input", str(input_macho), "--output", str(output_macho),
            "--report", str(kernel_report)
        ], check=True)
        patched_kernel = output_macho.read_bytes()
        detail = json.loads(kernel_report.read_text())
    if (len(patched_kernel) != MACHO_LENGTH or sha(patched_kernel) != OUTPUT_MACHO_SHA
            or detail["patched_sha256"] != OUTPUT_MACHO_SHA
            or not detail["only_fourth_checkpoint_modified"]):
        raise ValueError("Post-patch kernel verification failed")
    diff_indices = [i for i, (a,b) in enumerate(zip(original_kernel, patched_kernel)) if a != b]
    if (len(diff_indices) != 78 or min(diff_indices) < 0x3EC784
            or max(diff_indices) >= 0x3EC7D8):
        raise ValueError("Unexpected locations or number of kernel differences")
    for i in diff_indices:
        cl = clusters[i // cluster_len]
        dest_pos = cluster_pos(cl) + i % cluster_len
        if fat[dest_pos] != original_kernel[i]:
            raise AssertionError("Unexpected FAT32 byte at patch site")
        fat[dest_pos] = patched_kernel[i]
    reread = b"".join(
        bytes(fat[cluster_pos(cl):cluster_pos(cl) + cluster_len]) for cl in clusters
    )[:MACHO_LENGTH]
    if sha(reread) != OUTPUT_MACHO_SHA or sha(boot) != OUTPUT_BOOT_SHA:
        raise ValueError("Final boot.img SHA mismatch: refusing publication")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(boot)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "source_boot_sha256": SOURCE_BOOT_SHA,
        "patched_boot_sha256": OUTPUT_BOOT_SHA,
        "source_macho_sha256": SOURCE_MACHO_SHA,
        "patched_macho_sha256": OUTPUT_MACHO_SHA,
        "changed_bytes": len(diff_indices),
        "changed_byte_window_macho_file_offsets": ["0x3ec784", "0x3ec7d8"],
        "only_fat_macho_payload_changed": True,
        "working_edk2_binary_unchanged": True,
        "boot_v4": 4,
        "size": BOOT_LENGTH,
        "MMU_enabled_on_hardware": False,
    }, indent=2) + "\n")
    print(f"CHECK PASS: boot-v4 SHA256={OUTPUT_BOOT_SHA}; only 78 Mach-O bytes changed")

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    a = p.parse_args()
    main(a.input, a.output, a.report)

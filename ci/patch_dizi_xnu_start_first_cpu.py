#!/usr/bin/env python3
"""Dizi-only proof of reaching original start_first_cpu, in a pinned Mach-O COPY.

Input must be the previously verified WHITE first-opcode image. Hook the exact
first instruction at start_first_cpu with a branch to a checked, empty code cave
at Mach-O entry+0x80. Re-execute that original instruction in the trampoline,
draw a CYAN 9-row stripe at GOP Y240, and return to start_first_cpu+4.

Stages: MAGENTA = post EBS; GREEN = DarwinEnter pre-MMU; WHITE = injected
Mach-O entry; CYAN = first instruction of native start_first_cpu replayed.
None of these by itself establishes successful XNU initialization.
Never patch the original source Mach-O or shipping UEFI image.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

MARK = "DIZI_XNU_START_FIRST_CPU_CYAN_V1"
INPUT_SHA256 = "867b82d1445ebf6c505dbad92345efa60a34a01cad37dde3b375f103691160eb"
ENTRY_VA = 0xFFFFFFF0073F0488
NATIVE_VA = 0xFFFFFFF0073F205C
NATIVE_FIRST_WORD = 0xD510109F
CAVE_VA = ENTRY_VA + 0x80
CAVE_DELTA = 0x80
GOP_BASE = 0xB8000000
GOP_Y = 240
ROW_BYTES = 6400

def arm_branch(at: int, dest: int) -> int:
    disp = dest - at
    if disp % 4 or not -(1 << 27) <= disp < (1 << 27):
        raise ValueError("ARM64 branch out of range")
    return 0x14000000 | ((disp >> 2) & 0x3FFFFFF)

def executable_offset(data: bytes, va: int) -> int:
    if struct.unpack_from("<I", data, 0)[0] != 0xFEEDFACF:
        raise ValueError("Not a 64-bit Mach-O")
    ncmds, cmds_size = struct.unpack_from("<II", data, 16)
    if not 0 < ncmds < 256 or cmds_size > len(data) - 32:
        raise ValueError("Invalid load command bounds")
    pos = 32
    for _ in range(ncmds):
        cmd, cmd_size = struct.unpack_from("<II", data, pos)
        if cmd_size < 8 or pos + cmd_size > len(data):
            raise ValueError("Invalid load command")
        if cmd == 0x19:
            name, seg_va, vm_size, file_off, file_size = struct.unpack_from(
                "<16sQQQQ", data, pos + 8
            )
            if (name.rstrip(b"\0") == b"__TEXT_EXEC" and
                seg_va <= va < seg_va + min(vm_size, file_size)):
                ofs = file_off + (va - seg_va)
                if ofs + 0x100 > file_off + file_size:
                    raise ValueError("Insufficient file-backed executable text")
                return ofs
        pos += cmd_size
    raise ValueError(f"VA {va:#x} not in __TEXT_EXEC")

def make_trampoline() -> bytearray:
    clang = shutil.which("clang-18") or shutil.which("clang")
    objcopy = shutil.which("llvm-objcopy-18") or shutil.which("llvm-objcopy")
    if not clang or not objcopy:
        raise RuntimeError("clang + llvm-objcopy required")
    # GOP 0xB8000000 + 240 * 6400 = B8177000.
    # Replayed instruction (0xD510109F) comes FIRST: the CYAN band therefore
    # proves that original first instruction was executed by our trampoline.
    source = """
.section .text.cyan_probe, "ax", %progbits
.global dizi_start_first_cpu_probe
dizi_start_first_cpu_probe:
  .inst 0xd510109f
  movz x9, #0x7000
  movk x9, #0xb817, lsl #16
  movz w10, #0xffff
  movk w10, #0xff00, lsl #16
  movz w11, #7200
1:
  stp w10, w10, [x9], #8
  subs w11, w11, #1
  b.ne 1b
  dsb sy
  nop
"""
    with tempfile.TemporaryDirectory(prefix="dizi-cyan-") as t:
        p = Path(t)
        (p / "probe.S").write_text(source)
        subprocess.run([clang, "--target=aarch64-none-elf", "-c",
                        str(p / "probe.S"), "-o", str(p / "probe.o")], check=True)
        subprocess.run([objcopy, "-O", "binary", "-j", ".text.cyan_probe",
                        str(p / "probe.o"), str(p / "probe.bin")], check=True)
        return bytearray((p / "probe.bin").read_bytes())

def patch(source: Path, output: Path, report: Path):
    if source.resolve() == output.resolve():
        raise ValueError("Never overwrite an input Mach-O")
    data = bytearray(source.read_bytes())
    incoming_hash = hashlib.sha256(data).hexdigest()
    if incoming_hash != INPUT_SHA256:
        raise ValueError(f"Expected pinned WHITE marker image, got {incoming_hash}")
    entry_off = executable_offset(data, ENTRY_VA)
    native_off = executable_offset(data, NATIVE_VA)
    cave_off = entry_off + CAVE_DELTA
    if struct.unpack_from("<I", data, native_off)[0] != NATIVE_FIRST_WORD:
        raise ValueError("Pinned start_first_cpu first opcode changed")
    # Existing WHITE entry branch/trampoline must still be installed and
    # its original tail must point to start_first_cpu (from white cave +36).
    if struct.unpack_from("<I", data, entry_off)[0] != arm_branch(ENTRY_VA, ENTRY_VA + 0x40):
        raise ValueError("WHITE entry marker is missing")
    if struct.unpack_from("<I", data, entry_off + 0x40 + 36)[0] != arm_branch(
            ENTRY_VA + 0x40 + 36, NATIVE_VA):
        raise ValueError("WHITE marker does not retain native target branch")
    payload = make_trampoline()
    if len(payload) < 36 or len(payload) > 0xA0 or len(payload) % 4 != 0:
        raise ValueError(f"Unacceptable cyan trampoline size {len(payload)}")
    if struct.unpack_from("<I", payload, 0)[0] != NATIVE_FIRST_WORD:
        raise ValueError("Trampoline does not begin with exact displaced native instruction")
    if struct.unpack_from("<I", payload, len(payload) - 4)[0] != 0xD503201F:
        raise ValueError("Missing final NOP for return branch")
    if any(data[cave_off:cave_off + len(payload)]):
        raise ValueError("Cyan cave occupied")
    # Replace last NOP by branch to the original instruction+4. This
    # retains every following original instruction, but not a guarantee
    # that subsequent native code will execute successfully.
    struct.pack_into("<I", payload, len(payload) - 4,
                     arm_branch(CAVE_VA + len(payload) - 4, NATIVE_VA + 4))
    original = bytes(data[native_off:native_off + 4])
    struct.pack_into("<I", data, native_off, arm_branch(NATIVE_VA, CAVE_VA))
    data[cave_off:cave_off + len(payload)] = payload

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    out_hash = hashlib.sha256(data).hexdigest()
    assert output.stat().st_size == source.stat().st_size
    assert struct.unpack_from("<I", data, native_off)[0] == arm_branch(NATIVE_VA, CAVE_VA)
    assert struct.unpack_from("<I", data, cave_off + len(payload) - 4)[0] == arm_branch(
        CAVE_VA + len(payload) - 4, NATIVE_VA + 4)
    result = {
        "marker": MARK, "source_white_sha256": incoming_hash,
        "cyan_patched_sha256": out_hash, "source_bytes": len(data),
        "kernel_entry_va": hex(ENTRY_VA),
        "native_start_first_cpu_va": hex(NATIVE_VA),
        "native_first_instruction_replayed": original.hex(),
        "trampoline_va": hex(CAVE_VA), "trampoline_bytes": len(payload),
        "white_band_y": [220, 229], "cyan_band_y": [240, 248],
        "stage_meaning": "CYAN means original first instruction of start_first_cpu replayed; NOT proof native XNU initialized",
        "original_source_macho_untouched": True,
        "runtime_verified": False, "cpu_count_requested": 1,
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()
    patch(a.input, a.output, a.report)

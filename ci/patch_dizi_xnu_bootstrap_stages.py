#!/usr/bin/env python3
"""Dizi boot-args/bootstrap checkpoints after confirmed CYAN start_first_cpu.

Patches a COPY of the SHA-pinned PRE-MMU experiment:
- correct prior purported orange 0xFF00A5FF to true 0xFFFFA500
- five small independent markers at selected original XNU instructions
  before/after boot_args loads, zeroed page table, mapping completion,
  and _set_mmu_ttb return.
Each marker paints its own colored 9-row bar by direct physical GOP stores,
replays EXACTLY the displaced original instruction, then branches to +4.
Scratch x9-x11 are dead at all chosen sites in this pinned assembly;
no stack dependencies and no branch into a patched-away instruction.
Orange at y260 is STILL just a point BEFORE the SCTLR MSR.
Original source Mach-O and permanent EDK2 never altered.
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

SOURCE_SHA="de29ffc668de50ddef7fe4ac2f49b992eb3531512e750ee81143e1ab46fd7d9e"
ENTRY=0xFFFFFFF0073F0488
GOP=0xB8000000
ROW_BYTES=6400
CAVE_START=ENTRY+0x120
STAGES=[
    ("BEFORE_BOOT_ARGS_LOAD", 0xFFFFFFF0073F2078, 0xF9400696, 288, 0xFFFF0000),
    ("AFTER_BOOT_ARGS_LOAD",  0xFFFFFFF0073F208C, 0xD51BD07F, 312, 0xFFFFFF00),
    ("AFTER_PAGETABLE_ZERO", 0xFFFFFFF0073F20F0, 0xD0FFE080, 336, 0xFF00FF00),
    ("PAGE_MAP_COMPLETED",   0xFFFFFFF0073F2290, 0x90FFEBC0, 360, 0xFF0066FF),
    ("AFTER_SET_MMU_TTB",    0xFFFFFFF0073F22AC, 0xAA1303FE, 384, 0xFF9900FF),
]
MARK="DIZI_XNU_EARLY_BOOTSTRAP_FIVE_BANDS_V1"

def arm_b(frm:int,to:int)->int:
    diff=to-frm
    if diff%4 or not -(1<<27)<=diff<(1<<27):
        raise ValueError("AArch64 branch outside range")
    return 0x14000000 | ((diff>>2)&0x3ffffff)

def text_offset(data:bytes,addr:int)->int:
    if struct.unpack_from("<I",data)[0]!=0xFEEDFACF:
        raise ValueError("Mach-O header mismatch")
    n,cmd_bytes=struct.unpack_from("<II",data,16)
    if not 0<n<256 or cmd_bytes>len(data)-32:
        raise ValueError("Invalid Mach-O load commands")
    pos=32
    for _ in range(n):
        kind,size=struct.unpack_from("<II",data,pos)
        if size<8 or pos+size>len(data):
            raise ValueError("Malformed Mach-O load command")
        if kind==0x19:
            name,vm,vm_size,off,file_size=struct.unpack_from("<16sQQQQ",data,pos+8)
            if name.rstrip(b"\0")==b"__TEXT_EXEC" and vm<=addr<vm+min(vm_size,file_size):
                ofs=off+(addr-vm)
                if ofs>len(data)-4:raise ValueError("Executable address outside file")
                return ofs
        pos+=size
    raise ValueError("Not file-backed executable VA: "+hex(addr))

def assemble(asm:str)->bytearray:
    clang=shutil.which("clang-18") or shutil.which("clang")
    objcopy=shutil.which("llvm-objcopy-18") or shutil.which("llvm-objcopy")
    if not clang or not objcopy:raise RuntimeError("clang and llvm-objcopy required")
    with tempfile.TemporaryDirectory(prefix="dizi-stages-") as tmp:
        p=Path(tmp)
        (p/"probe.S").write_text(asm)
        subprocess.run([clang,"--target=aarch64-none-elf","-c",str(p/"probe.S"),"-o",str(p/"probe.o")],check=True)
        subprocess.run([objcopy,"-O","binary","-j",".text.probe",str(p/"probe.o"),str(p/"probe.bin")],check=True)
        return bytearray((p/"probe.bin").read_bytes())

def body(target:int, color:int, original:int)->bytearray:
    addr=GOP+target*ROW_BYTES
    if not (GOP<=addr and addr+(9*ROW_BYTES)<=GOP+2560*ROW_BYTES):
        raise ValueError("GOP rectangle outside visible framebuffer")
    asm=f"""
.section .text.probe, "ax", %progbits
.global trace
trace:
  movz x9, #{addr & 0xffff}
  movk x9, #{(addr >> 16) & 0xffff}, lsl #16
  movz w10, #{color & 0xffff}
  movk w10, #{(color >> 16) & 0xffff}, lsl #16
  movz w11, #7200
1:
  stp w10, w10, [x9], #8
  subs w11, w11, #1
  b.ne 1b
  dsb sy
  .inst {original:#x}
  nop
"""
    return assemble(asm)

def patch(inp:Path,out:Path,report:Path)->None:
    if inp.resolve()==out.resolve():
        raise ValueError("Refusing in-place modification")
    data=bytearray(inp.read_bytes())
    if hashlib.sha256(data).hexdigest()!=SOURCE_SHA:
        raise ValueError("Wrong pinned pre-MMU input kernel SHA256")
    entry=text_offset(data,ENTRY)
    if struct.unpack_from("<I",data,entry)[0]!=arm_b(ENTRY,ENTRY+0x40):
        raise ValueError("Previous WHITE marker missing")
    if struct.unpack_from("<I",data,text_offset(data,0xFFFFFFF0073F205C))[0]!=arm_b(0xFFFFFFF0073F205C,ENTRY+0x80):
        raise ValueError("Previous CYAN marker missing")
    if struct.unpack_from("<I",data,text_offset(data,0xFFFFFFF0073F234C))[0]!=arm_b(0xFFFFFFF0073F234C,ENTRY+0xC0):
        raise ValueError("Previous pre-MMU ORANGE hook missing")
    if struct.unpack_from("<II",data,text_offset(data,0xFFFFFFF0073F2350))!=(0xD5181000,0xD5033FDF):
        raise ValueError("Original SCTLR MSR/ISB unexpectedly changed")

    # Correct color words in the EXISTING pre-MMU probe; leave its
    # control flow and register save/restore/branch unchanged.
    old=struct.unpack_from("<II",data,entry+0xE0)
    if old!=(0x5294BFEA,0x72BFE00A):
        raise ValueError("Pinned old pre-MMU color code changed")
    corrected=assemble("""
.section .text.probe, "ax", %progbits
  movz w10, #0xa500
  movk w10, #0xffff, lsl #16
""")
    if len(corrected)!=8:
        raise ValueError("Color-only patch must be two instructions")
    data[entry+0xE0:entry+0xE8]=corrected

    plans=[]
    current=CAVE_START
    for name,site,oldword,y,color in STAGES:
        ofs=text_offset(data,site)
        if struct.unpack_from("<I",data,ofs)[0]!=oldword:
            raise ValueError("Expected pinned instruction missing: "+name)
        payload=body(y,color,oldword)
        if len(payload)!=44:
            raise ValueError(f"Unexpected {name} marker size {len(payload)}, expected 44")
        dest=text_offset(data,current)
        if any(data[dest:dest+len(payload)]):
            raise ValueError("Marker code cave occupied at "+hex(current))
        struct.pack_into("<I",payload,len(payload)-4,arm_b(current+len(payload)-4,site+4))
        struct.pack_into("<I",data,ofs,arm_b(site,current))
        data[dest:dest+len(payload)]=payload
        plans.append({"name":name,"hook_va":hex(site),"original_word":hex(oldword),
                      "stub_va":hex(current),"y":[y,y+8],"argb":hex(color)})
        current+=len(payload)
    if current>ENTRY+0x200:
        raise AssertionError("Tracing cave overrun")
    if struct.unpack_from("<II",data,text_offset(data,0xFFFFFFF0073F2350))!=(0xD5181000,0xD5033FDF):
        raise AssertionError("SCTLR/ISB no longer original")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(data)
    outcome={
        "marker":MARK,"source_sha256":SOURCE_SHA,
        "patched_sha256":hashlib.sha256(data).hexdigest(),
        "source_bytes":len(data),"stages":plans,
        "orange_fixed_from":"0xff00a5ff",
        "orange_corrected_to":"0xffffa500",
        "orange_y":[260,268],
        "mmu_msr_isb_unchanged":True,
        "original_source_untouched":True,
        "xnu_mmu_boot_success_confirmed":False,
        "interpretation":"Last visible colored bar identifies last reached site; missing bar alone is not definitive proof of fault location"
    }
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(outcome,indent=2)+"\n")
    print(json.dumps(outcome,indent=2))

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    a=ap.parse_args()
    patch(a.input,a.output,a.report)

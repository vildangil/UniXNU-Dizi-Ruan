#!/usr/bin/env python3
"""Pinned dizi Mach-O first-instruction probe, on a COPY only.

White GOP band Y220-229 proves patched Mach-O entry executed after
DarwinEnter's EL1 MMU-off branch. NOT proof original XNU kernel booted.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, struct, subprocess, tempfile
from pathlib import Path

MARK="DIZI_XNU_ENTRY_WHITE_STRIPE_V1"
SHA="49eed545945df805b6f004eaecc496575072184c6335efea1f5b11ea50feda42"
ENTRY=0xfffffff0073f0488
TARGET=0xfffffff0073f205c

def arm_b(at,to):
    diff=to-at
    if diff%4 or not -(1<<27)<=diff<(1<<27):
        raise ValueError("Arm64 branch not reachable")
    return 0x14000000 | ((diff>>2)&0x3ffffff)

def get_entry_offset(data):
    if struct.unpack_from("<I",data)[0]!=0xfeedfacf:
        raise ValueError("not an arm64 Mach-O")
    ncmds,cmdsize=struct.unpack_from("<II",data,16)
    if not 0<ncmds<256 or cmdsize>len(data)-32:
        raise ValueError("bad load commands")
    pos=32; segments=[]; pc=None
    for i in range(ncmds):
        cmd,size=struct.unpack_from("<II",data,pos)
        if size<8 or pos+size>len(data):raise ValueError("bad load command")
        if cmd==0x19:
            name,vm,vm_sz,ofs,sz=struct.unpack_from("<16sQQQQ",data,pos+8)
            segments.append((name.strip(b'\0'),vm,vm_sz,ofs,sz))
        elif cmd==5:
            if size<280 or pc is not None:raise ValueError("invalid LC_UNIXTHREAD")
            pc=struct.unpack_from("<Q",data,pos+272)[0]
        pos+=size
    if pc!=ENTRY:raise ValueError("unexpected entry VA")
    for name,vm,vm_sz,ofs,sz in segments:
        if vm<=ENTRY<vm+min(vm_sz,sz) and ofs+ENTRY-vm+0x100<=ofs+sz:
            if name!=b'__TEXT_EXEC':raise ValueError("entry not in text")
            return ofs+ENTRY-vm
    raise ValueError("entry not file-backed")

def make_code():
    clang=shutil.which("clang-18") or shutil.which("clang")
    objcopy=shutil.which("llvm-objcopy-18") or shutil.which("llvm-objcopy")
    if not clang or not objcopy:raise RuntimeError("need clang and llvm-objcopy")
    # Real physical GOP 0xB8000000, Y220 at 0xB8157C00, 6400-byte stride
    asm="""// DIZI_XNU_ENTRY_WHITE_STRIPE_V1
.section .text.entry_probe, "ax", %progbits
.global dizi_entry_probe
dizi_entry_probe:
  movz x9, #0x7c00
  movk x9, #0xb815, lsl #16
  movz w10, #0xffff
  movk w10, #0xffff, lsl #16
  movz w11, #7200
1:
  stp w10, w10, [x9], #8
  subs w11, w11, #1
  b.ne 1b
  dsb sy
  nop
"""
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)
        (p/"a.S").write_text(asm)
        subprocess.run([clang,"--target=aarch64-none-elf","-c",str(p/"a.S"),"-o",str(p/"a.o")],check=True)
        subprocess.run([objcopy,"-O","binary","-j",".text.entry_probe",str(p/"a.o"),str(p/"a.bin")],check=True)
        return bytearray((p/"a.bin").read_bytes())

def main(src,dst,report):
    if src.resolve()==dst.resolve():raise ValueError("refusing in-place patch")
    data=bytearray(src.read_bytes())
    sha=hashlib.sha256(data).hexdigest()
    if sha!=SHA:raise ValueError(f"pinned kernel SHA mismatch: {sha}")
    ofs=get_entry_offset(data)
    original=struct.unpack_from("<I",data,ofs)[0]
    if original!=0x140006f5 or arm_b(ENTRY,TARGET)!=original:
        raise ValueError("pinned original entry opcode changed")
    payload=make_code()
    if len(payload)<32 or len(payload)>0xb0 or len(payload)%4:
        raise ValueError("invalid trampoline length")
    cave=ofs+0x40
    if any(data[cave:cave+len(payload)]):
        raise ValueError("code cave occupied")
    if struct.unpack_from("<I",payload,len(payload)-4)[0]!=0xd503201f:
        raise ValueError("final NOP not found")
    struct.pack_into("<I",payload,len(payload)-4,arm_b(ENTRY+0x40+len(payload)-4,TARGET))
    struct.pack_into("<I",data,ofs,arm_b(ENTRY,ENTRY+0x40))
    data[cave:cave+len(payload)]=payload
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_bytes(data)
    result={
        "marker":MARK,"source_sha256":sha,"patched_sha256":hashlib.sha256(data).hexdigest(),
        "file_bytes":len(data),"entry_va":hex(ENTRY),"original_target":hex(TARGET),
        "trampoline_va":hex(ENTRY+0x40),"trampoline_bytes":len(payload),
        "entry_file_offset":hex(ofs),"gop_physical":"0xb8000000","white_band_y":[220,229],
        "original_kernel_not_modified":True,"xnu_executed_on_device":False,
        "meaning":"White = instrumented kernel image entry code executed, not proof native XNU initialized"
    }
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))

if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--report",type=Path,required=True)
    a=ap.parse_args()
    main(a.input,a.output,a.report)

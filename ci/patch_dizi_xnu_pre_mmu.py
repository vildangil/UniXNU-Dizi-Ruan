#!/usr/bin/env python3
"""Dizi pre-MMU checkpoint: patch SHA-pinned Mach-O COPY only.

Temporarily replace MOVK at 0xFFFFFFF0073F234C with a branch to
an empty code cave. Replay MOVK, paint ORANGE GOP Y260..268,
restore registers/flags, then branch to ORIGINAL MSR SCTLR_EL1
at +4, which is never patched. Orange means reached immediately
before the XNU MMU enable; not that MMU was actually enabled.
"""
import argparse, hashlib, json, pathlib, shutil, struct, subprocess, tempfile
SRC="1d200a2e544f0bb766081f9a2682df24fd39cf30873278ec2d78b2725eb8251d"
ENTRY=0xfffffff0073f0488
HOOK=0xfffffff0073f234c
MSR=HOOK+4
CAVE=ENTRY+0xc0
MOVK=0xf28b27a0
SCTLR=0xd5181000
ISB=0xd5033fdf
def b_ins(frm,to):
    d=to-frm
    if d%4 or not -(1<<27)<=d<(1<<27):raise ValueError("Branch out of range")
    return 0x14000000 | ((d>>2)&0x3ffffff)
def off(blob,va):
    if struct.unpack_from("<I",blob)[0]!=0xfeedfacf:raise ValueError("Not Mach-O")
    n,size=struct.unpack_from("<II",blob,16)
    if not 0<n<256 or size>len(blob)-32:raise ValueError("Bad LC header")
    p=32
    for _ in range(n):
        typ,sz=struct.unpack_from("<II",blob,p)
        if sz<8 or p+sz>len(blob):raise ValueError("Bad LC")
        if typ==0x19:
            name,addr,vm,fo,fs=struct.unpack_from("<16sQQQQ",blob,p+8)
            if name.rstrip(b"\0")==b"__TEXT_EXEC" and addr<=va<addr+min(vm,fs):
                return fo+(va-addr)
        p+=sz
    raise ValueError("Not in __TEXT_EXEC "+hex(va))
def assemble():
    clang=shutil.which("clang-18") or shutil.which("clang")
    obj=shutil.which("llvm-objcopy-18") or shutil.which("llvm-objcopy")
    if not clang or not obj:raise RuntimeError("Cross LLVM tools missing")
    asm="""
.section .text.mmu, "ax", %progbits
.global mmu_probe
mmu_probe:
  .inst 0xf28b27a0
  sub sp, sp, #48
  stp x9, x10, [sp, #0]
  stp x11, x12, [sp, #16]
  mrs x12, nzcv
  str x12, [sp, #32]
  movz x9, #0x6400
  movk x9, #0xb819, lsl #16
  movz w10, #0xa5ff
  movk w10, #0xff00, lsl #16
  movz w11, #7200
1:
  stp w10, w10, [x9], #8
  subs w11, w11, #1
  b.ne 1b
  dsb sy
  ldr x12, [sp, #32]
  msr nzcv, x12
  ldp x11, x12, [sp, #16]
  ldp x9, x10, [sp, #0]
  add sp, sp, #48
  nop
"""
    with tempfile.TemporaryDirectory() as t:
        p=pathlib.Path(t)
        (p/"a.S").write_text(asm)
        subprocess.run([clang,"--target=aarch64-none-elf","-c",str(p/"a.S"),"-o",str(p/"a.o")],check=True)
        subprocess.run([obj,"-O","binary","-j",".text.mmu",str(p/"a.o"),str(p/"a.bin")],check=True)
        return bytearray((p/"a.bin").read_bytes())
def main(inp,out,report):
    if inp.resolve()==out.resolve():raise ValueError("Cannot overwrite source")
    data=bytearray(inp.read_bytes())
    sha=hashlib.sha256(data).hexdigest()
    if sha!=SRC:raise ValueError("Pinned cyan Mach-O SHA mismatch "+sha)
    h=off(data,HOOK);c=off(data,CAVE)
    if struct.unpack_from("<III",data,h)!=(MOVK,SCTLR,ISB):
        raise ValueError("Unexpected pre-MMU MOVK/MSR/ISB")
    native=0xfffffff0073f205c
    if struct.unpack_from("<I",data,off(data,native))[0]!=b_ins(native,ENTRY+0x80):
        raise ValueError("Previous cyan marker missing")
    if struct.unpack_from("<I",data,off(data,ENTRY))[0]!=b_ins(ENTRY,ENTRY+0x40):
        raise ValueError("Previous white marker missing")
    code=assemble()
    if not 64<=len(code)<=0xc0 or len(code)%4:raise ValueError("Bad code size")
    if struct.unpack_from("<I",code)[0]!=MOVK or struct.unpack_from("<I",code,len(code)-4)[0]!=0xd503201f:
        raise ValueError("Missing displaced MOVK or return placeholder")
    if any(data[c:c+len(code)]) or c+len(code)>off(data,ENTRY+0x200):
        raise ValueError("Code cave occupied")
    struct.pack_into("<I",code,len(code)-4,b_ins(CAVE+len(code)-4,MSR))
    struct.pack_into("<I",data,h,b_ins(HOOK,CAVE))
    data[c:c+len(code)]=code
    if struct.unpack_from("<II",data,h+4)!=(SCTLR,ISB):
        raise AssertionError("MSR/ISB modified")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(data)
    info={"marker":"DIZI_XNU_PRE_MMU_ORANGE_V2","source_cyan_sha256":sha,
          "patched_sha256":hashlib.sha256(data).hexdigest(),"file_bytes":len(data),
          "hook_va":hex(HOOK),"displaced_replayed_word":hex(MOVK),
          "msr_va":hex(MSR),"msr_isb_untouched":True,
          "trampoline_va":hex(CAVE),"trampoline_bytes":len(code),
          "gop_base":"0xb8000000","orange_band_y":[260,268],
          "source_untouched":True,"mmu_enabled_on_device":False,
          "meaning":"ORANGE = XNU reached instruction immediately BEFORE MMU enable"}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(info,indent=2)+"\n")
    print(json.dumps(info,indent=2))
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",type=pathlib.Path,required=True)
    ap.add_argument("--output",type=pathlib.Path,required=True)
    ap.add_argument("--report",type=pathlib.Path,required=True)
    a=ap.parse_args()
    main(a.input,a.output,a.report)

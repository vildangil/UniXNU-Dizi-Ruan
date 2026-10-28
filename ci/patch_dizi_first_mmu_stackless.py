#!/usr/bin/env python3
"""Replace only first post-TTB trace stub with SP-independent version.

Hardware #40649020254 showed the previous purple Y384 stripe, but not
the first NEW pink Y408 stripe. All six NEW stubs used SP; all five OLD
stubs were stackless. In a PINNED COPY of the exact six-stub Mach-O,
replace only the first 84-byte stub at __start+0x200. It draws pink
using x9/x10/x11 as earlier successful stubs did, replays the displaced
original AND, then returns to original TTBR1_EL1 MSR.
This is a diagnostic, not a safe general-purpose XNU fix.
"""
import argparse, hashlib, json, shutil, struct, subprocess, tempfile
from pathlib import Path

SHA="cc4da0da3850c23d1498c343c836387f4d68342e9f0ed8da4ae4b079c8a693e7"
MARK="DIZI_FIRST_MMU_STAGE_STACKLESS_V1"
STUB=0xfffffff0073f0688
NEXT=0xfffffff0073f06dc
HOOK=0xfffffff0073f22b4
AND=0x9240bc00
def branch(a,b):
    d=b-a
    if d%4 or not -(1<<27)<=d<1<<27:raise ValueError("unreachable branch")
    return 0x14000000|((d>>2)&0x3ffffff)
def fileoff(blob,va):
    if struct.unpack_from("<I",blob)[0]!=0xfeedfacf:raise ValueError("Not Mach-O64")
    n,size=struct.unpack_from("<II",blob,16)
    if not 0<n<256 or size+32>len(blob):raise ValueError("Invalid load commands")
    p=32
    for _ in range(n):
        kind,sz=struct.unpack_from("<II",blob,p)
        if sz<8 or p+sz>len(blob):raise ValueError("Bad load command")
        if kind==0x19:
            name,base,vsize,fo,fs=struct.unpack_from("<16sQQQQ",blob,p+8)
            if name.rstrip(b"\0")==b"__TEXT_EXEC" and base<=va<base+min(vsize,fs):
                return fo+va-base
        p+=sz
    raise ValueError("Missing executable address "+hex(va))
def assemble():
    cc=shutil.which("clang-18") or shutil.which("clang")
    obj=shutil.which("llvm-objcopy-18") or shutil.which("llvm-objcopy")
    if not cc or not obj:raise RuntimeError("LLVM cross tools required")
    asm="""
.section .text.nosp,"ax",%progbits
.global dizi_post_ttb_nosp
dizi_post_ttb_nosp:
  movz x9, #0xd800
  movk x9, #0xb827, lsl #16
  movz w10, #0x1493
  movk w10, #0xffff, lsl #16
  movz w11, #7200
1:
  stp w10, w10, [x9], #8
  subs w11, w11, #1
  b.ne 1b
  dsb sy
  .inst 0x9240bc00
  nop
"""
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)
        (p/"a.S").write_text(asm)
        subprocess.run([cc,"--target=aarch64-none-elf","-c",str(p/"a.S"),"-o",str(p/"a.o")],check=True)
        subprocess.run([obj,"-O","binary","-j",".text.nosp",str(p/"a.o"),str(p/"a.bin")],check=True)
        code=bytearray((p/"a.bin").read_bytes())
    if len(code)!=44 or struct.unpack_from("<II",code,36)!=(AND,0xd503201f):
        raise ValueError("Unexpected compiled code")
    struct.pack_into("<I",code,40,branch(STUB+40,HOOK+4))
    size=NEXT-STUB
    if size!=84:raise ValueError("Unexpected original stub size")
    code+=struct.pack("<I",0xd503201f)*((size-len(code))//4)
    if len(code)!=size:raise ValueError("Mis-sized replacement")
    return code
def main(src,dst,report):
    if src.resolve()==dst.resolve():raise ValueError("Refuse in-place source overwrite")
    blob=bytearray(src.read_bytes())
    hash0=hashlib.sha256(blob).hexdigest()
    if hash0!=SHA:raise ValueError("Exact six-stage kernel SHA mismatch "+hash0)
    start,end,hook=(fileoff(blob,v) for v in (STUB,NEXT,HOOK))
    if end-start!=84:raise ValueError("Unexpected cave layout")
    if struct.unpack_from("<I",blob,start)[0]!=0xd100c3ff:
        raise ValueError("First six-stage stub does not use SP")
    if struct.unpack_from("<I",blob,end)[0]!=0xd100c3ff:
        raise ValueError("Second six-stage stub changed")
    if struct.unpack_from("<I",blob,hook)[0]!=branch(HOOK,STUB):
        raise ValueError("Hook does not reach first stub")
    for va,words in [
        (0xfffffff0073f22b8,(0xd5182020,)),
        (0xfffffff0073f2350,(0xd5181000,0xd5033fdf))
    ]:
        if struct.unpack_from("<"+"I"*len(words),blob,fileoff(blob,va))!=words:
            raise ValueError("Expected original MMU system register instruction missing")
    second=bytes(blob[end:end+84])
    blob[start:end]=assemble()
    if bytes(blob[end:end+84])!=second:raise AssertionError("Second probe unexpectedly modified")
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_bytes(blob)
    info={
        "marker":MARK,"source_six_stage_sha256":hash0,
        "patched_sha256":hashlib.sha256(blob).hexdigest(),
        "file_bytes":len(blob),"first_stage_stub_va":hex(STUB),
        "first_stage_hook_va":hex(HOOK),"returns_to":hex(HOOK+4),
        "modified_bytes":84,"no_sp_in_first_stage":True,
        "other_five_probes_unchanged":True,"first_stage_pink_y":[408,416],
        "original_and_replayed":hex(AND),"native_ttb_msr_untouched":True,
        "native_sctlr_isb_untouched":True,"source_untouched":True,
        "early_stack_validity_confirmed":False,
        "interpretation":"Pink with this but not the six-stage test supports an early-SP problem. x9-x11/NZCV are clobbered as in earlier stackless probes; HIGH RISK diagnostic only."
    }
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(info,indent=2)+"\n")
    print(json.dumps(info,indent=2))
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args()
    main(a.input,a.output,a.report)

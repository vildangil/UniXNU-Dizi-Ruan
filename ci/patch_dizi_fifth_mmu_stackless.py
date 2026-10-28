#!/usr/bin/env python3
"""Dizi: ONLY fifth (Y504) MMU checkpoint goes stackless on pinned FOUR-NOSP Mach-O.

Replays original ADD x0,x0,#0. Previous four probes and final sixth stackful
probe remain byte identical. No source Mach-O or firmware change. Diagnostic
clobbers x9/x10/x11/NZCV, not proof of MMU-on kernel startup.
"""
from __future__ import annotations
import argparse,hashlib,json,struct
from pathlib import Path
SOURCE_SHA="b1ec254a0038208cad8ce4284ff759a33b096436208505cafc3e084be4361fa3"
OUTPUT_SHA="6758750c684e0569eea1c00be6726bb1409f6a3c0327a555de21b3b3d134f97c"
MARK="DIZI_FIFTH_MMU_STAGE_STACKLESS_V1"
ENTRY=0xfffffff0073f0488
FOURTH=ENTRY+0x2fc
FIFTH=ENTRY+0x350
SIXTH=ENTRY+0x3a4
HOOK=0xfffffff0073f2330
ORIGINAL=0x91000000
TTBR1=0xfffffff0073f22b8
SCTLR=0xfffffff0073f2350
def branch(a,b):
    d=b-a
    if d%4 or not -(1<<27)<=d<(1<<27):raise ValueError("Bad ARM64 B range")
    return 0x14000000|((d>>2)&0x3ffffff)
def offset(b,va):
    if struct.unpack_from("<I",b)[0]!=0xfeedfacf:raise ValueError("Not Mach-O64")
    n,cmdlen=struct.unpack_from("<II",b,16)
    if not 0<n<256 or cmdlen>len(b)-32:raise ValueError("Bad Mach-O command table")
    p=32
    for _ in range(n):
        cmd,sz=struct.unpack_from("<II",b,p)
        if sz<8 or p+sz>len(b):raise ValueError("Bad Mach-O command")
        if cmd==0x19:
            name,vm,vsize,fo,filesize=struct.unpack_from("<16sQQQQ",b,p+8)
            if name.rstrip(b'\0')==b"__TEXT_EXEC" and vm<=va<vm+min(vsize,filesize):
                out=fo+va-vm
                if not 0<=out<=len(b)-4:raise ValueError("Bad file offset")
                return out
        p+=sz
    raise ValueError("VA not file-backed executable: "+hex(va))
def patch(src,dst,report):
    if src.resolve()==dst.resolve():raise ValueError("No in-place patch")
    b=bytearray(src.read_bytes());sha=hashlib.sha256(b).hexdigest()
    if sha!=SOURCE_SHA:raise ValueError("Pinned FOUR-NOSP input SHA mismatch: "+sha)
    fourth,fifth,sixth=(offset(b,a) for a in (FOURTH,FIFTH,SIXTH))
    if fifth-fourth!=84 or sixth-fifth!=84:raise ValueError("Unexpected stub layout")
    if struct.unpack_from("<I",b,fourth)[0]!=0xd29c0009:raise ValueError("FOURTH no-SP missing")
    if struct.unpack_from("<I",b,fifth)[0]!=0xd100c3ff:raise ValueError("FIFTH old SP probe missing")
    if struct.unpack_from("<I",b,sixth)[0]!=0xd100c3ff:raise ValueError("SIXTH old SP probe missing")
    if struct.unpack_from("<I",b,offset(b,HOOK))[0]!=branch(HOOK,FIFTH):raise ValueError("FIFTH native hook changed")
    if struct.unpack_from("<I",b,offset(b,TTBR1))[0]!=0xd5182020:raise ValueError("TTBR1 changed")
    if struct.unpack_from("<II",b,offset(b,SCTLR))!=(0xd5181000,0xd5033fdf):raise ValueError("SCTLR/ISB changed")
    w=list(struct.unpack_from("<21I",b,fifth))
    if w[:5]!=[0xd100c3ff,0xa9002be9,0xa90133eb,0xd53b420c,0xf90013ec]:
        raise ValueError("Original fifth SP prelude changed")
    draw=[0xd2870009,0xf2b70629,0x5297ffea,0x72bff00a,
          0x5283840b,0x2881292a,0x7100056b,0x54ffffc1,0xd5033f9f]
    if w[5:14]!=draw:raise ValueError("Original Y504 draw changed")
    if w[19]!=ORIGINAL or w[20]!=branch(FIFTH+80,HOOK+4):
        raise ValueError("Original displaced ADD/return changed")
    new=draw+[ORIGINAL,branch(FIFTH+40,HOOK+4)]+[0xd503201f]*10
    if len(new)!=21:raise AssertionError("Stub must be 84 bytes")
    old=bytes(b);b[fifth:sixth]=struct.pack("<21I",*new)
    if b[:fifth]!=old[:fifth] or b[sixth:]!=old[sixth:]:raise AssertionError("Out-of-bounds modification")
    changed=sum(a!=c for a,c in zip(old,b))
    if changed!=80:raise ValueError("Changed byte count mismatch: "+str(changed))
    output_hash=hashlib.sha256(b).hexdigest()
    if output_hash!=OUTPUT_SHA:raise ValueError("Patched Mach-O hash mismatch: "+output_hash)
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(b)
    meta={"marker":MARK,"source_sha256":sha,"patched_sha256":output_hash,"size":len(b),
          "changed_bytes":changed,"modified_region_bytes":84,
          "fifth_stub_va":hex(FIFTH),"fifth_hook_va":hex(HOOK),"returns_to":hex(HOOK+4),
          "fifth_light_blue_y":[504,512],"original_add_replayed":hex(ORIGINAL),
          "only_fifth_checkpoint_modified":True,
          "previous_four_stubs_preserved":True,"sixth_stack_stub_preserved":True,
          "native_ttbr1_sctlr_isb_untouched":True,"mmu_enabled_on_hardware":False}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(meta,indent=2)+"\n")
    print(json.dumps(meta,indent=2))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    a=p.parse_args();patch(a.input,a.output,a.report)

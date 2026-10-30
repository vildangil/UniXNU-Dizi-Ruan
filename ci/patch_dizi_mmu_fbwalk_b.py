#!/usr/bin/env python3
"""Dizi XNU: pin and switch walk-b to read TTBR0 framebuffer mapping, pre-MMU.

No UEFI replacement, new code, SP use, framebuffer writes after SCTLR,
or page-table modifications. All changes stay in the existing traced cave.
Temporary fastboot boot ONLY, NEVER flash.
"""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

BOOT_BYTES=68800512
KERNEL_OFFSET=0x19c000+0x101200
KERNEL_BYTES=51941376
CAVE_VA=0xfffffff0073f0488+0x500
CAVE_BYTES=1584
BASE_BOOT_SHA='8c5c1aba446897a7548461a05718d79ddfb5607cfd0745c5187d423ed3a05542'
BASE_KERNEL_SHA='00e522094ba5981f3520279f5b33611cfce1aac17f1156ab2b6b6362aaa30270'
OUT_BOOT_SHA='e16a4c797a1afdebfe3b7bd61b47bc79a64a24c769d2c77f5a5bda4be948887b'
OUT_KERNEL_SHA='bee3a4d609965fc0a65423ff5080fdcaa0a8e9fa70f134517ebc9327d630d426'
# Offsets are relative to the already-traced 1569-byte walk-b code cave.
# Old/new AArch64 encodings checked with clang + llvm-objdump.
WORDS=(
 (0x40,0xd538202b,0xd538200b),  # mrs x11,TTBR1 -> mrs x11,TTBR0
 (0x98,0xd5382030,0xd5382010),  # pre-read guard checks TTBR0
 (0x9c,0xd29c0005,0xd29a0005),  # expected low 16: E000 -> D000
 (0xcc,0xf943020f,0xf9400a0f),  # L1 entry TTBR0 + 0x10 (idx 0x02)
 (0xf8,0xf940e60f,0xf947020f),  # L2 index 0x1C0; offset 0xE00
 (0x12c,0xf947ca0f,0xf940020f), # optional L3 FB page zero
 (0x140,0xf947b60f,0xf940060f), # optional L3 FB page one
)
TEXT=(
 (b'DIZI / XNU PT WALK B', b'DIZI / XNU FB WALK B'),
 (b'TTBR1:',b'TTBR0:'),
 (b'L3 PC:',b'L3 FB:'),
 (b'L3 VBR:',b'L3 FB1:'),
 (b'L1 INDEX C0 L2 INDEX 39',b'FB ROOT 02 L2 INDEX 1C0'),
)

sha=lambda b:hashlib.sha256(b).hexdigest()


def kernel_va_offset(blob:bytes,addr:int)->int:
    if struct.unpack_from('<I',blob)[0]!=0xfeedfacf:
        raise ValueError('Unexpected Mach-O format')
    n,length=struct.unpack_from('<II',blob,16)
    if not 0<n<256 or length>len(blob)-32:
        raise ValueError('Invalid Mach-O commands')
    p=32
    for _ in range(n):
        kind,size=struct.unpack_from('<II',blob,p)
        if size<8 or p+size>32+length:raise ValueError('Invalid Mach-O command length')
        if kind==0x19:
            name,va,vsize,off,fsize=struct.unpack_from('<16sQQQQ',blob,p+8)
            if name.rstrip(b'\0')==b'__TEXT_EXEC' and va<=addr<va+min(vsize,fsize):
                return off+addr-va
        p+=size
    raise ValueError('Code-cave VA missing')


def build(source:Path,dest:Path,audit:Path):
    if source.resolve()==dest.resolve():raise ValueError('Cannot patch input in place')
    boot=source.read_bytes()
    if len(boot)!=BOOT_BYTES or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4 or sha(boot)!=BASE_BOOT_SHA:
        raise ValueError('Refusing image other than verified walk-b boot')
    old=boot[KERNEL_OFFSET:KERNEL_OFFSET+KERNEL_BYTES]
    if sha(old)!=BASE_KERNEL_SHA:raise ValueError('Unexpected Mach-O bytes')
    k=bytearray(old)
    start=kernel_va_offset(k,CAVE_VA)
    end=kernel_va_offset(k,CAVE_VA+CAVE_BYTES)
    if end-start!=CAVE_BYTES:raise ValueError('Unexpected cave geometry')
    region=bytearray(k[start:end])
    for offset,before,after in WORDS:
        actual=struct.unpack_from('<I',region,offset)[0]
        if actual!=before:raise ValueError(f'Unexpected ARM64 word at {offset:#x}: {actual:#x}')
        struct.pack_into('<I',region,offset,after)
    for before,after in TEXT:
        if len(before)!=len(after):raise ValueError('Text edit length changed')
        if region.count(before)!=1:raise ValueError(f'Unexpected text count for {before!r}')
        region=region.replace(before,after,1)
    k[start:end]=region
    # Prove no other Mach-O bytes were changed.
    changes=[i for i,(x,y) in enumerate(zip(old,k)) if x!=y]
    if not changes or any(not(start<=i<end) for i in changes):
        raise ValueError('Patch changed native XNU code outside old cave')
    out=bytearray(boot)
    for i in changes:out[KERNEL_OFFSET+i]=k[i]
    bh,mh=sha(out),sha(k)
    if OUT_BOOT_SHA and bh!=OUT_BOOT_SHA:raise ValueError('Boot hash mismatch: '+bh)
    if OUT_KERNEL_SHA and mh!=OUT_KERNEL_SHA:raise ValueError('Mach-O hash mismatch: '+mh)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes(out)
    audit.parent.mkdir(parents=True,exist_ok=True)
    report={
        'variant':'fbwalk-b','boot_sha256':bh,'macho_sha256':mh,
        'source_walk_b_sha256':BASE_BOOT_SHA,'modified_macho_bytes':len(changes),
        'ttbr0_observed':'0x802F6D000','framebuffer_va_to_test':'0xB8000000',
        'l1_index':2,'l2_index':448,'l3_first_indices':[0,1],
        'sctlr_isb_modified':False,'after_mmu_framebuffer_access':False,
        'hardware_tested':False,'note':'Read-only pre-MMU TTBR0 walk; output block must be independently checked before post-MMU GOP access.',
        'warning':'HIGH-RISK. fastboot boot only, NEVER fastboot flash.'
    }
    audit.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();build(args.input,args.output,args.report)

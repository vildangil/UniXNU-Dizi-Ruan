#!/usr/bin/env python3
"""SHA-pinned dizi read-only pre-SCTLR guard-stage diagnostic.

Show actual 64-bit data for the first failed check among eight invariants,
or ALL CHECKS PASS. NO page-table writes and NO post-MMU framebuffer access.
High-risk hardware testing: temporary fastboot boot ONLY; NEVER flash.
"""
from __future__ import annotations
import argparse, json, shutil, struct, subprocess, tempfile
from pathlib import Path
import patch_dizi_mmu_alias_b as a

BASE_BOOT = a.BASE_BOOT_SHA
BASE_MACHO = a.BASE_MACHO_SHA
OUTPUT_BOOT = '17e9504f4737d4b483df5c9d4fbd85d07a5829fd6fe3d711b9f0a3530ac8fba3'
OUTPUT_MACHO = '7fc9719c6d5205a911be58244e5242c55c3b6821bb4ec2756ff70b2a2ec69b6f'
SYMBOLS = ('dizi_entry_trampoline','dizi_pre_trampoline','entry_resume','pre_resume')
OFFSET = getattr(a,'code_offset',None) or getattr(a,'off')
BRANCH = getattr(a,'branch',None) or getattr(a,'arm_b')
FONT_OFFSET = 700
FONT_BYTES = 413
STAGES = {1:'TCR_EL1',2:'TTBR1_EL1',3:'VBAR_EL1',4:'MAIR_EL1',
          5:'SCTLR_EL1.M already set',6:'L1 kernel descriptor',
          7:'L2 kernel descriptor',8:'Alias slot L2 not empty'}

def compile_guard(m:bytes):
    start=OFFSET(m,a.CAVE)
    font=m[start+FONT_OFFSET:start+FONT_OFFSET+FONT_BYTES]
    if len(font)!=413 or a.sha(font)!=a.FONT_SHA:
        raise ValueError('Expected physical text-b font')
    asm=Path(__file__).with_name('dizi_mmu_guard_b.S.in').read_text()
    if asm.count('FONT_DATA')!=1:raise ValueError('Font insertion point invalid')
    asm=asm.replace('FONT_DATA','.byte '+','.join(str(x) for x in font))
    clang=shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    nm=shutil.which('nm')
    if not all((clang,objcopy,nm,shutil.which('readelf'))):
        raise RuntimeError('clang/llvm-objcopy/nm/readelf required')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)
        (p/'trace.S').write_text(asm)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(p/'trace.S'),'-o',str(p/'trace.o')],check=True)
        rel=subprocess.check_output(['readelf','-r',str(p/'trace.o')],text=True)
        if 'There are no relocations in this file' not in rel:
            raise ValueError('Probe has unresolved ARM64 relocations')
        symbols={}
        for line in subprocess.check_output([nm,'-n',str(p/'trace.o')],text=True).splitlines():
            x=line.split()
            if len(x)==3 and x[2] in SYMBOLS:symbols[x[2]]=int(x[0],16)
        if len(symbols)!=len(SYMBOLS):raise ValueError('Incomplete probe labels')
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(p/'trace.o'),str(p/'trace.bin')],check=True)
        data=bytearray((p/'trace.bin').read_bytes())
    if a.CAVE+len(data)>=a.VECTOR_START or len(data)>a.CAVE_END-a.CAVE:
        raise ValueError('Probe spills into XNU exception vectors')
    if struct.unpack_from('<I',data,symbols['dizi_pre_trampoline'])[0]!=0xf28b27a0:
        raise ValueError('Missing original MOVK x0')
    for label,target in (('entry_resume',a.FIRST),('pre_resume',a.SCTLR)):
        pos=symbols[label]
        if struct.unpack_from('<I',data,pos)[0]!=0xd503201f:raise ValueError('Missing return slot')
        struct.pack_into('<I',data,pos,BRANCH(a.CAVE+pos,target))
    return data,symbols

def build(src:Path,dest:Path,report:Path):
    if src.resolve()==dest.resolve():raise ValueError('In-place modifications forbidden')
    boot=src.read_bytes()
    if len(boot)!=a.BOOT_SIZE or a.sha(boot)!=BASE_BOOT or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4:
        raise ValueError('Source is not exact hardware-tested SLOT-B boot-v4')
    fat=memoryview(boot)[0x19c000:0x19c000+64*1024*1024]
    if fat[82:87].tobytes()!=b'FAT32':raise ValueError('Unexpected FAT32 layout')
    original=boot[a.KERNEL_OFFSET:a.KERNEL_OFFSET+a.KERNEL_SIZE]
    if a.sha(original)!=BASE_MACHO:raise ValueError('Unexpected original Mach-O')
    k=bytearray(original);o=lambda va:OFFSET(k,va)
    if struct.unpack_from('<II',k,o(a.SCTLR))!=(0xd5181000,0xd5033fdf):raise ValueError('SCTLR/ISB altered')
    if struct.unpack_from('<II',k,o(0xfffffff0073f2368))!=(0xeb01001f,0x54000001):raise ValueError('Native comparison altered')
    if struct.unpack_from('<I',k,o(a.ENTRY))[0]!=BRANCH(a.ENTRY,a.CAVE):raise ValueError('Entry hook changed')
    if struct.unpack_from('<I',k,o(a.PRE))[0]!=BRANCH(a.PRE,a.CAVE+16):raise ValueError('Pre-SCTLR hook changed')
    if struct.unpack_from('<I',k,o(a.POST))[0]!=0xf2e00001 or struct.unpack_from('<I',k,o(a.GUARD))[0]!=0xd2a00600:
        raise ValueError('Post-SCTLR native opcodes changed')
    code,symbols=compile_guard(k)
    start,end=o(a.CAVE),o(a.CAVE_END)
    if end-start!=1584:raise ValueError('Unexpected pre-vector cave length')
    k[start:end]=bytes(end-start)
    k[start:start+len(code)]=code
    for site,label in ((a.ENTRY,'dizi_entry_trampoline'),(a.PRE,'dizi_pre_trampoline')):
        struct.pack_into('<I',k,o(site),BRANCH(site,a.CAVE+symbols[label]))
    allowed=set(range(start,end))
    for site in (a.ENTRY,a.PRE):allowed.update(range(o(site),o(site)+4))
    changed=[i for i,(x,y) in enumerate(zip(original,k)) if x!=y]
    if not changed or any(i not in allowed for i in changed):raise ValueError('Probe escaped diagnostic cave and entry hooks')
    out=bytearray(boot)
    for i in changed:out[a.KERNEL_OFFSET+i]=k[i]
    if a.sha(out)!=OUTPUT_BOOT or a.sha(k)!=OUTPUT_MACHO:
        raise ValueError('Output differs from independently verified image')
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(out)
    data={'variant':'guard-b','source_boot_sha256':BASE_BOOT,'output_boot_sha256':OUTPUT_BOOT,
          'output_macho_sha256':OUTPUT_MACHO,'changed_macho_bytes':len(changed),
          'probe_size':len(code),'failure_steps':STAGES,'writes_to_page_tables':False,
          'post_mmu_fb_access':False,'native_sctlr_isb_cmp_bne_unchanged':True,
          'hardware_tested':False,'warning':'HIGH RISK, temporary fastboot boot ONLY; NEVER flash.'}
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps(data,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    x=p.parse_args();build(x.input,x.output,x.report)

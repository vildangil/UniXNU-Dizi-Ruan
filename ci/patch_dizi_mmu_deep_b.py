#!/usr/bin/env python3
"""SHA-pinned B-series XNU handoff diagnostics plus read-only boot MPIDR.

Only tested slot-b's tracer cave and eight native one-instruction hook sites
are changed. After MMU-on, text writes use the existing guarded high-VA
Device framebuffer alias. No PSCI CPU_ON, additional MMIO or page changes.
HIGH RISK: temporary fastboot boot only; never flash.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, struct, subprocess, tempfile
from pathlib import Path
import patch_dizi_mmu_alias_b as base

SOURCE_BOOT='ab1edbbc8b05fe9b59f0f6909ce84c75faf40c1c98edea6acb50d268c9e688ee'
SOURCE_MACHO='9e0f5f1411d674879ceedad09736e941349d487bb4836949e8a3bc51c4289662'
EXPECTED_BOOT='4acf22fe3b0fb389ccc057b591b7c41fc57e0e0c32eaa246342f34e85c232c45'
EXPECTED_MACHO='0248d8724fa4978dd2391088d82e06c9ed1130829d1d77f20229eb512a1abecd'
CAVE=0xfffffff0073f0988
CAVE_END=CAVE+1584
SCTLR=0xfffffff0073f2350
HOODS=(
 (0xfffffff0073f0488, 'dizi_entry_trampoline',None),
 (0xfffffff0073f234c, 'dizi_pre_trampoline',None),
 (0xfffffff0073f2358, 'dizi_post_trampoline',0xf2e00001),
 (0xfffffff0073f2370, 'dizi_guard_trampoline',0xd2a00600),
 (0xfffffff0073f2378, 'dizi_tpidr_trampoline',0xd518d09f),
 (0xfffffff0073f2388, 'dizi_return_trampoline',0xd65f03c0),
 (0xfffffff0073f239c, 'dizi_branch_trampoline',0xd61f0000),
 (0xfffffff0079b3404, 'dizi_arm_init_trampoline',0xd10343ff),
)
RETURNS={
 'entry_resume':0xfffffff0073f205c,
 'pre_resume':SCTLR,
 'post_resume':0xfffffff0073f235c,
 'guard_resume':0xfffffff0073f2374,
 'tpidr_resume':0xfffffff0073f237c,
 'arm_init_resume':0xfffffff0079b3408,
}
ORIGINAL_REPLAY={
 'dizi_pre_trampoline':0xf28b27a0,
 'dizi_post_trampoline':0xf2e00001,
 'dizi_guard_trampoline':0xd2a00600,
 'dizi_tpidr_trampoline':0xd518d09f,
 'dizi_arm_init_trampoline':0xd10343ff,
 'return_resume':0xd65f03c0,
 'branch_resume':0xd61f0000,
}
SHA=lambda b:hashlib.sha256(b).hexdigest()
OFFSET=getattr(base,'code_offset',None) or getattr(base,'off',None)
BRANCH=getattr(base,'branch',None) or getattr(base,'arm_b',None)
if OFFSET is None or BRANCH is None:raise RuntimeError('Pinned base patcher ABI changed')

def assemble(kernel:bytes):
    start=OFFSET(kernel,CAVE)
    font=kernel[start+700:start+1113]
    if len(font)!=413 or SHA(font)!='71d8475b427a59edaca1ad55592e83812e7fe5c7f8be8444ffc1d3733d303501':
        raise ValueError('Missing SHA-pinned slot-b physical framebuffer font')
    raw=Path(__file__).with_name('dizi_mmu_deep_b.S.in').read_text()
    if raw.count('FONT_DATA')!=1:raise ValueError('Invalid assembly font placeholder')
    raw=raw.replace('FONT_DATA','.byte '+','.join(map(str,font)))
    clang=shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    nm=shutil.which('nm')
    if not clang or not objcopy or not nm or not shutil.which('readelf'):
        raise RuntimeError('Requires clang, llvm-objcopy, readelf and nm')
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)
        (folder/'stub.S').write_text(raw)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(folder/'stub.S'),'-o',str(folder/'stub.o')],check=True)
        reloc=subprocess.check_output(['readelf','-r',str(folder/'stub.o')],text=True)
        if 'There are no relocations in this file' not in reloc:raise ValueError('Unexpected AArch64 relocations')
        symbols={}
        for line in subprocess.check_output([nm,'-n',str(folder/'stub.o')],text=True).splitlines():
            fields=line.split()
            if len(fields)==3 and (fields[2] in RETURNS or fields[2] in ORIGINAL_REPLAY or fields[2] in [x[1] for x in HOODS]):
                symbols[fields[2]]=int(fields[0],16)
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(folder/'stub.o'),str(folder/'stub.bin')],check=True)
        code=bytearray((folder/'stub.bin').read_bytes())
    if not all(key in symbols for key in set(RETURNS)|set(ORIGINAL_REPLAY)|{x[1] for x in HOODS}):
        raise ValueError('Unexpected missing ARM64 symbol')
    if len(code)>1584 or CAVE+len(code)>=0xfffffff0073f1000:raise ValueError('Tracer would overwrite exception vectors')
    for name,opcode in ORIGINAL_REPLAY.items():
        if struct.unpack_from('<I',code,symbols[name])[0]!=opcode:
            raise ValueError('Displaced native instruction not replayed: '+name)
    for name,target in RETURNS.items():
        at=symbols[name]
        if struct.unpack_from('<I',code,at)[0]!=0xd503201f:raise ValueError('Expected return NOP: '+name)
        struct.pack_into('<I',code,at,BRANCH(CAVE+at,target))
    if (296+28)*6400+4400>=2*1024*1024:raise ValueError('Diagnostic exceeds mapped framebuffer')
    return bytes(code),symbols

def build(src:Path,dst:Path,report:Path):
    if src.resolve()==dst.resolve():raise ValueError('In-place patch forbidden')
    boot=src.read_bytes()
    if len(boot)!=68800512 or SHA(boot)!=SOURCE_BOOT or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4:
        raise ValueError('Need exact hardware-tested SLOT-B boot-v4 image')
    old=boot[base.KERNEL_OFFSET:base.KERNEL_OFFSET+base.KERNEL_SIZE]
    if SHA(old)!=SOURCE_MACHO:raise ValueError('Unexpected Mach-O source')
    kernel=bytearray(old)
    off=lambda va:OFFSET(kernel,va)
    if struct.unpack_from('<II',kernel,off(SCTLR))!=(0xd5181000,0xd5033fdf):raise ValueError('Native SCTLR/ISB changed')
    if struct.unpack_from('<II',kernel,off(0xfffffff0073f2368))!=(0xeb01001f,0x54000001):raise ValueError('Native CMP/B.NE changed')
    if struct.unpack_from('<I',kernel,off(HOODS[0][0]))[0]!=BRANCH(HOODS[0][0],CAVE):raise ValueError('Original entry hook mismatch')
    if struct.unpack_from('<I',kernel,off(HOODS[1][0]))[0]!=BRANCH(HOODS[1][0],CAVE+16):raise ValueError('Original pre-SCTLR hook mismatch')
    for va,_,op in HOODS[2:]:
        if struct.unpack_from('<I',kernel,off(va))[0]!=op:raise ValueError('Unexpected native hook site '+hex(va))
    trace,sym=assemble(old)
    lo,hi=off(CAVE),off(CAVE_END)
    if hi-lo!=1584:raise ValueError('Diagnostic code cave unexpectedly changed')
    kernel[lo:hi]=bytes(hi-lo)
    kernel[lo:lo+len(trace)]=trace
    for va,name,_ in HOODS:struct.pack_into('<I',kernel,off(va),BRANCH(va,CAVE+sym[name]))
    allowed=set(range(lo,hi))
    for va,_,_ in HOODS:allowed.update(range(off(va),off(va)+4))
    changes=[i for i,(x,y) in enumerate(zip(old,kernel)) if x!=y]
    if not changes or any(i not in allowed for i in changes):raise ValueError('Mutation outside native tracer/hooks')
    out=bytearray(boot)
    for i in changes:out[base.KERNEL_OFFSET+i]=kernel[i]
    bh,mh=SHA(out),SHA(kernel)
    if bh!=EXPECTED_BOOT or mh!=EXPECTED_MACHO:raise ValueError('Build does not match independently pinned SHA: '+bh+' / '+mh)
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(out)
    details={'variant':'deep-b','hardware_tested':False,'source_slot_b_sha256':SOURCE_BOOT,
             'boot_sha256':bh,'macho_sha256':mh,'trace_bytes':len(trace),
             'modified_macho_bytes':len(changes),
             'new_hardware_checkpoints':['TPIDR DONE','RETURN TO ARM_INIT','SECONDARY BRANCH','ARM_INIT CPU0 or OTHER CPU'],
             'cpu_affinity':'MPIDR_EL1 Aff0:Aff2 sampled at _arm_init; no secondary CPU_ON',
             'preserves_native_sctlr_cmp_and_mmu_alias_guard':True,
             'existing_alias_l2_mapping_only':True,
             'safety':'HIGH RISK; temporary fastboot boot only, never fastboot flash.'}
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(details,indent=2)+'\n')
    print(json.dumps(details,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

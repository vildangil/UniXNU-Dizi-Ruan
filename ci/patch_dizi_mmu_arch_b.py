#!/usr/bin/env python3
"""Read-only ARM64 system-register audit at hardware-confirmed _arm_init entry.

Inherits SHA-pinned deep-b's MMU-on, TPIDR, handoff and _arm_init hooks.
Modifies ONLY the previous 1584-byte executable diagnostics cave.
No page-table changes compared to deep-b; no CPU_ON, no extra MMIO.
HIGH RISK: temporary fastboot boot only; never fastboot flash.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, struct, subprocess, tempfile
from pathlib import Path
import patch_dizi_mmu_deep_b as deep

SOURCE_BOOT='4acf22fe3b0fb389ccc057b591b7c41fc57e0e0c32eaa246342f34e85c232c45'
SOURCE_MACHO='0248d8724fa4978dd2391088d82e06c9ed1130829d1d77f20229eb512a1abecd'
EXPECTED_BOOT='58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b'
EXPECTED_MACHO='af2e080430be9a41bf608d51551086720704a4fca18a3a796948c6778c05c6c9'
FONT_SHA='71d8475b427a59edaca1ad55592e83812e7fe5c7f8be8444ffc1d3733d303501'
FONT_DEEP_OFFSET=0x3cc
TRACE_CAVE_BYTES=1584
EXPECTED_TRACE_BYTES=1581
RETURN_TAGS={
 'entry_resume':0xfffffff0073f205c,
 'pre_resume':0xfffffff0073f2350,
 'post_resume':0xfffffff0073f235c,
 'guard_resume':0xfffffff0073f2374,
 'tpidr_resume':0xfffffff0073f237c,
 'arm_init_resume':0xfffffff0079b3408,
}
ORIGINAL_NATIVE={
 'dizi_pre_trampoline':0xf28b27a0,
 'dizi_post_trampoline':0xf2e00001,
 'dizi_guard_trampoline':0xd2a00600,
 'dizi_tpidr_trampoline':0xd518d09f,
 'dizi_arm_init_trampoline':0xd10343ff,
 'return_resume':0xd65f03c0,
 'branch_resume':0xd61f0000,
}
sha=lambda b:hashlib.sha256(b).hexdigest()

def assemble(original:bytes):
    off=deep.OFFSET(original,deep.CAVE)
    font=original[off+FONT_DEEP_OFFSET:off+FONT_DEEP_OFFSET+413]
    if len(font)!=413 or sha(font)!=FONT_SHA:
        raise ValueError('Expected hardware-confirmed deep-b 5x7 font')
    src=Path(__file__).with_name('dizi_mmu_arch_b.S.in').read_text()
    if src.count('FONT_DATA')!=1:raise ValueError('Font placeholder count changed')
    src=src.replace('FONT_DATA','.byte '+','.join(str(x) for x in font))
    clang=shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    if not all([clang,objcopy,shutil.which('nm'),shutil.which('readelf')]):
        raise RuntimeError('clang, llvm-objcopy, nm and readelf are required')
    with tempfile.TemporaryDirectory() as tmp:
        work=Path(tmp)
        (work/'arch.S').write_text(src)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(work/'arch.S'),'-o',str(work/'arch.o')],check=True)
        reloc=subprocess.check_output(['readelf','-r',str(work/'arch.o')],text=True)
        if 'There are no relocations in this file' not in reloc:
            raise ValueError('Unexpected AArch64 relocations')
        symbols={}
        keys=set(RETURN_TAGS)|set(ORIGINAL_NATIVE)
        for line in subprocess.check_output(['nm','-n',str(work/'arch.o')],text=True).splitlines():
            entry=line.split()
            if len(entry)==3 and entry[2] in keys:symbols[entry[2]]=int(entry[0],16)
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(work/'arch.o'),str(work/'arch.bin')],check=True)
        buf=bytearray((work/'arch.bin').read_bytes())
    if len(buf)!=EXPECTED_TRACE_BYTES or len(buf)>TRACE_CAVE_BYTES or set(symbols)!=keys:
        raise ValueError('Unexpected ARM64 diagnostic cave size/labels')
    for name,opcode in ORIGINAL_NATIVE.items():
        if struct.unpack_from('<I',buf,symbols[name])[0]!=opcode:
            raise ValueError('Original instruction not replayed: '+name)
    for name,destination in RETURN_TAGS.items():
        pos=symbols[name]
        if struct.unpack_from('<I',buf,pos)[0]!=0xd503201f:
            raise ValueError('Expected return NOP '+name)
        struct.pack_into('<I',buf,pos,deep.BRANCH(deep.CAVE+pos,destination))
    for token in ('mrs x9, CurrentEL','mrs x9, CNTFRQ_EL0',
                  'mrs x9, SCTLR_EL1','mrs x9, TPIDR_EL1','mrs x9, MIDR_EL1'):
        if token not in src:raise ValueError('Missing architectural read: '+token)
    return bytes(buf)

def build(src:Path,dst:Path,report:Path):
    if src.resolve()==dst.resolve():raise ValueError('In-place patch forbidden')
    boot=src.read_bytes()
    if len(boot)!=68800512 or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4 or sha(boot)!=SOURCE_BOOT:
        raise ValueError('Expected exact hardware-tested deep-b boot-v4')
    original=boot[deep.base.KERNEL_OFFSET:deep.base.KERNEL_OFFSET+deep.base.KERNEL_SIZE]
    if sha(original)!=SOURCE_MACHO:raise ValueError('Deep-b Mach-O hash mismatch')
    if struct.unpack_from('<II',original,deep.OFFSET(original,0xfffffff0073f2350))!=(0xd5181000,0xd5033fdf):
        raise ValueError('Native SCTLR_EL1 or ISB modified')
    code=assemble(original)
    kernel=bytearray(original)
    lo=deep.OFFSET(kernel,deep.CAVE)
    hi=deep.OFFSET(kernel,deep.CAVE_END)
    if hi-lo!=TRACE_CAVE_BYTES:raise ValueError('Unexpected traced cave geometry')
    kernel[lo:hi]=bytes(TRACE_CAVE_BYTES)
    kernel[lo:lo+len(code)]=code
    changes=[i for i,(x,y) in enumerate(zip(original,kernel)) if x!=y]
    if not changes or any(i<lo or i>=hi for i in changes):
        raise ValueError('Patch escaped hardware-tested diagnostic cave')
    output=bytearray(boot)
    for i in changes:output[deep.base.KERNEL_OFFSET+i]=kernel[i]
    bh,mh=sha(output),sha(kernel)
    if bh!=EXPECTED_BOOT or mh!=EXPECTED_MACHO:
        raise ValueError('Output SHA disagrees with locally audited build: '+bh+' / '+mh)
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_bytes(output)
    record={'variant':'arch-b','hardware_tested':False,
            'source_deep_b_sha256':SOURCE_BOOT,'output_boot_sha256':bh,
            'output_macho_sha256':mh,'code_bytes':len(code),
            'changed_kernel_bytes':len(changes),
            'checks':['MPIDR Aff0-Aff2 == 0','CurrentEL == EL1',
                      'CNTFRQ_EL0 == 19,200,000','SCTLR_EL1.M == 1',
                      'TPIDR_EL1 == 0','MIDR_EL1 nonzero'],
            'page_table_changes_relative_to_deep_b':False,
            'additional_psci_cpu_on':False,'additional_gic_mmio':False,
            'success_message':'ARCH REGS OK','failure_message':'ARCH REGS FAIL',
            'warning':'HIGH-RISK; temporary fastboot boot ONLY, never flash'}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    build(a.input,a.output,a.report)

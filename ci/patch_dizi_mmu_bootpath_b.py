#!/usr/bin/env python3
"""SHA-locked Dizi bootpath-b 4-stage XNU _arm_init progress probe.

Starts from the physically tested arch-b boot (already confirmed MMU-on,
CurrentEL/19.2MHz/TPIDR/MIDR checks). Reuses its guarded high-VA
Device framebuffer alias and 5x7 renderer. Replaces only the prior
ARM_INIT-only diagnostic mini-stubs, their four fixed-width strings,
and seven audited native one-instruction hook sites.

The four new sites are AFTER native calls: _cpu_data_init,
_ml_get_boot_cpu_number, _serial_init (and _arm_vm_init), and _PE_init_cpu.
The renderer overwrites the same status row with the latest milestone.
No PSCI CPU_ON, new page-table mapping, MMIO or kernel source replacement.
HIGH RISK. Temporary fastboot boot ONLY; never flash.
"""
from __future__ import annotations
import argparse,hashlib,json,struct
from pathlib import Path

SOURCE_BOOT='58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b'
SOURCE_MACHO='af2e080430be9a41bf608d51551086720704a4fca18a3a796948c6778c05c6c9'
OUTPUT_BOOT='332debe2cb36926e389c2519ea9b877b31b596761b6f462a80479f588f6dce2d'
OUTPUT_MACHO='b620bac2b139cbbaa1a97db7f66f67fae7223d5985d8fbd3c77394fb586243af'
KERNEL_START=0x19c000+0x101200
KERNEL_BYTES=51941376
BOOT_BYTES=68800512
RENDERER=0xfffffff0073f0bb4
CAVE_START=0xfffffff0073f0a20
CAVE_END=0xfffffff0073f0abc
RESTORE=(
 (0xfffffff0073f2388,0xd65f03c0),  # original ret
 (0xfffffff0073f239c,0xd61f0000),  # original br x0
 (0xfffffff0079b3404,0xd10343ff),  # original _arm_init SP prologue
)
# Native call completed, unused caller-saved registers available at site.
# Renderer does NOT clobber x0, x19, x20, x21, x30, SP or NZCV.
STAGES=(
 (0xfffffff0079b39ac,0xfffffff0073f0a20,6,0x52800000,'CPU DATA OK'),
 (0xfffffff0079b3a5c,0xfffffff0073f0a3c,9,0xb90002a0,'TOPO OK'),
 (0xfffffff0079b3b98,0xfffffff0073f0a58,7,0xaa0003f3,'VM SERIAL OK'),
 (0xfffffff0079b3d08,0xfffffff0073f0a74,8,0x52800020,'CPU INIT OK'),
)
DISPLAY=(
 (b'RETURN TO ARM_INIT',b'CPU DATA OK       '),
 (b'ALT BRANCH',b'TOPO OK   '),
 (b'ARCH REGS OK',b'VM SERIAL OK'),
 (b'ARCH REGS FAIL',b'CPU INIT OK   '),
)
sha=lambda b:hashlib.sha256(b).hexdigest()

def off(k:bytes,va:int)->int:
    if len(k)<1000 or struct.unpack_from('<I',k)[0]!=0xfeedfacf:
        raise ValueError('Expected Mach-O64')
    count,length=struct.unpack_from('<II',k,16)
    if not 0<count<256 or length>len(k)-32:raise ValueError('Invalid load commands')
    pos=32
    for _ in range(count):
        cmd,size=struct.unpack_from('<II',k,pos)
        if size<8 or pos+size>32+length:raise ValueError('Invalid load command')
        if cmd==0x19:
            name,base,vsize,foff,fsize=struct.unpack_from('<16sQQQQ',k,pos+8)
            if name.rstrip(b'\0')==b'__TEXT_EXEC' and base<=va<base+min(vsize,fsize):
                return foff+va-base
        pos+=size
    raise ValueError('Unexpected XNU code VA: '+hex(va))

def b(src:int,dst:int)->int:
    delta=dst-src
    if delta%4 or not -(1<<27)<=delta<(1<<27):raise ValueError('ARM64 branch out of range')
    return 0x14000000|((delta//4)&0x3ffffff)

def adr12(src:int,dst:int)->int:
    delta=dst-src
    if not -(1<<20)<=delta<(1<<20):raise ValueError('ARM64 ADR out of range')
    return 0x1000000c|((delta&3)<<29)|(((delta>>2)&0x7ffff)<<5)

def read(k:bytes,va:int)->int:return struct.unpack_from('<I',k,off(k,va))[0]
def write(k:bytearray,va:int,word:int):struct.pack_into('<I',k,off(k,va),word)

def build(src:Path,dst:Path,report:Path):
    if src.resolve()==dst.resolve():raise ValueError('Refusing in-place patch')
    boot=src.read_bytes()
    if len(boot)!=BOOT_BYTES or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4 or sha(boot)!=SOURCE_BOOT:
        raise ValueError('Input must be the exact hardware-confirmed arch-b boot')
    original=boot[KERNEL_START:KERNEL_START+KERNEL_BYTES]
    if sha(original)!=SOURCE_MACHO:raise ValueError('Unexpected source Mach-O')
    k=bytearray(original)
    if struct.unpack_from('<II',k,off(k,0xfffffff0073f2350))!=(0xd5181000,0xd5033fdf):
        raise ValueError('Native SCTLR/ISB changed')
    if struct.unpack_from('<II',k,off(k,0xfffffff0073f2368))!=(0xeb01001f,0x54000001):
        raise ValueError('Native compare guard changed')
    for va,original_op in RESTORE:
        if read(k,va)>>26!=0b000101:raise ValueError('Native old diagnostic hook changed')
        write(k,va,original_op)
    lo,hi=off(k,CAVE_START),off(k,CAVE_END)
    if hi-lo!=156:raise ValueError('Unexpected diagnostic cave geometry')
    k[lo:hi]=struct.pack('<I',0xd503201f)*39
    for site,stub,stage,native,_ in STAGES:
        if read(original,site)!=native:raise ValueError('Native boot stage opcode changed: '+hex(site))
        # Renderer returns via BR x12 to a native instruction replay
        # AFTER drawing, so PC-relative/arg state isn't accidentally overwritten.
        words=(adr12(stub,stub+0x14),0x5280000d|(stage<<5),
               b(stub+8,RENDERER),0xd503201f,0xd503201f,
               native,b(stub+0x18,site+4))
        for i,word in enumerate(words):write(k,stub+i*4,word)
        write(k,site,b(site,stub))
    allowed=set(range(lo,hi))
    for site,_ in RESTORE:allowed.update(range(off(k,site),off(k,site)+4))
    for site,_,_,_,_ in STAGES:allowed.update(range(off(k,site),off(k,site)+4))
    for former,replacement in DISPLAY:
        if len(former)!=len(replacement) or k.count(former)!=1:
            raise ValueError('Unexpected diagnostic marker layout')
        pos=original.find(former)
        if pos<0:raise ValueError('Missing original source message')
        allowed.update(range(pos,pos+len(former)))
        k=k.replace(former,replacement,1)
    diff=[i for i,(a,c) in enumerate(zip(original,k)) if a!=c]
    if not diff or any(i not in allowed for i in diff):
        raise ValueError('Modification outside traced code, strings and 7 hooks')
    if read(k,0xfffffff0079b3404)!=0xd10343ff:
        raise ValueError('Original _arm_init stack prologue not restored')
    result=bytearray(boot)
    for i in diff:result[KERNEL_START+i]=k[i]
    bh,mh=sha(result),sha(k)
    if (bh,mh)!=(OUTPUT_BOOT,OUTPUT_MACHO):
        raise ValueError('Boot/Mach-O SHA not reproduced: '+bh+' / '+mh)
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(result)
    report.parent.mkdir(parents=True,exist_ok=True)
    audit={'variant':'bootpath-b','hardware_tested':False,
           'source_arch_b_sha256':SOURCE_BOOT,'boot_sha256':bh,
           'macho_sha256':mh,'changed_macho_bytes':len(diff),
           'stages':[{'label':label,'native_hook_va':hex(va),'native_opcode':hex(op)}
                     for va,_,_,op,label in STAGES],
           'last_screen_line':'Latest reached: CPU DATA OK / TOPO OK / VM SERIAL OK / CPU INIT OK',
           'native_sctlr_cmp_unchanged':True,
           'additional_page_table_changes':False,'psci_cpu_on':False,
           'warning':'HIGH RISK: fastboot boot ONLY; never flash.'}
    report.write_text(json.dumps(audit,indent=2)+'\n')
    print(json.dumps(audit,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    x=p.parse_args();build(x.input,x.output,x.report)

#!/usr/bin/env python3
"""SHA-locked XNU FLOW-B: eight register/flags-preserving _arm_init checkpoints.

Uses precompiled, independently disassembled Arm64 tracer; no new MMIO,
PSCI CPU_ON or changes to native MMU/bootloader. Original code/flags restored.
The second code cave is a verified zero-padding region AFTER VBAR vectors.
Temporary fastboot boot only; NEVER flash. Hardware not yet tested.
"""
from __future__ import annotations
import argparse,base64,hashlib,json,struct
from pathlib import Path

SOURCE_BOOT='58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b'
SOURCE_MACHO='af2e080430be9a41bf608d51551086720704a4fca18a3a796948c6778c05c6c9'
PAYLOAD_SHA='dbdb592ce93c7ad750874c32423b14d4ffa7499ef54a82b3e880cd7bd73f2c6f'
OUTPUT_BOOT='3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c'
OUTPUT_MACHO='b740835898ca1be232e733c76af967a66fbe025c3b8e48f34c2febb8f889efc7'
BOOT_BYTES=68800512
MACHO_OFF=0x29d200
MACHO_BYTES=51941376
CAVE=0xfffffff0073f1800
CAVE_END=0xfffffff0073f1ff0
# Each site is an original native instruction in the verified arch-b image.
SITES=(
 ('PROLOGUE',0xfffffff0079b3424,0xaa0003f3),
 ('TBI RETURN',0xfffffff0079b3448,0x91000108),
 ('KC REBASE',0xfffffff0079b3984,0xaa1403e0),
 ('CPU DATA',0xfffffff0079b39a4,0xaa1303e0),
 ('PE PLATFORM',0xfffffff0079b39b0,0xaa1403e1),
 ('TIMER WFE',0xfffffff0079b39c8,0x52800020),
 ('CPU TOPO',0xfffffff0079b3a78,0x79000268),
 ('THREAD READY',0xfffffff0079b3abc,0xaa0003f4),
)
sha=lambda b:hashlib.sha256(b).hexdigest()

def off(blob:bytes,va:int)->int:
    if struct.unpack_from('<I',blob)[0]!=0xfeedfacf:raise ValueError('Expected Mach-O64')
    n,command_bytes=struct.unpack_from('<II',blob,16)
    if not 0<n<256 or command_bytes>len(blob)-32:raise ValueError('Invalid Mach-O load commands')
    cursor=32
    for _ in range(n):
        cmd,length=struct.unpack_from('<II',blob,cursor)
        if length<8 or cursor+length>32+command_bytes:raise ValueError('Corrupt load command')
        if cmd==0x19:
            name,base,vsize,fo,fs=struct.unpack_from('<16sQQQQ',blob,cursor+8)
            if name.rstrip(b'\0')==b'__TEXT_EXEC' and base<=va<base+min(vsize,fs):
                return fo+va-base
        cursor+=length
    raise ValueError('Executable VA not found: '+hex(va))

def branch(site:int,target:int)->int:
    delta=target-site
    if delta%4 or not -(1<<27)<=delta<(1<<27):raise ValueError('Branch outside B range')
    return 0x14000000|((delta>>2)&0x3ffffff)

def build(inp:Path,dst:Path,report:Path)->None:
    if inp.resolve()==dst.resolve():raise ValueError('Refusing source overwrite')
    boot=inp.read_bytes()
    if len(boot)!=BOOT_BYTES or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4 or sha(boot)!=SOURCE_BOOT:
        raise ValueError('Not exact hardware-tested arch-b boot-v4')
    orig=boot[MACHO_OFF:MACHO_OFF+MACHO_BYTES]
    if sha(orig)!=SOURCE_MACHO:raise ValueError('Unexpected embedded XNU Mach-O')
    if struct.unpack_from('<II',orig,off(orig,0xfffffff0073f2350))!=(0xd5181000,0xd5033fdf):
        raise ValueError('Native SCTLR_EL1 or ISB changed')
    start,end=off(orig,CAVE),off(orig,CAVE_END)
    if end-start!=CAVE_END-CAVE or any(orig[start:end]):
        raise ValueError('After-vector code cave is no longer all zero')
    payload=base64.b64decode(Path(__file__).with_name('dizi_mmu_flow_b_payload.b64').read_text().strip(),validate=True)
    if len(payload)!=1163 or sha(payload)!=PAYLOAD_SHA:raise ValueError('Arm64 payload integrity failure')
    # Each trampoline stores x12/x13, saves all caller registers and NZCV,
    # prints a separate stage on the existing verified Device high-VA alias,
    # restores state, then replays its displaced native instruction.
    for i,(stage,site,opcode) in enumerate(SITES):
        entry=i*28;resume=entry+16
        if struct.unpack_from('<I',payload,entry)[0]!=0xa9bf37ec:raise ValueError('Missing entry register save')
        if struct.unpack_from('<II',payload,resume)!=(0xa8c137ec,opcode):
            raise ValueError('Displaced instruction missing: '+stage)
        if struct.unpack_from('<I',payload,resume+8)[0]!=branch(CAVE+resume+8,site+4):
            raise ValueError('Wrong return branch: '+stage)
        if struct.unpack_from('<I',orig,off(orig,site))[0]!=opcode:
            raise ValueError('Unrecognized native site: '+stage)
    if struct.unpack_from('<I',payload,0x10c)[0]!=0xd53b4209 or struct.unpack_from('<I',payload,0x120)[0]!=0xd51b4209:
        raise ValueError('NZCV register save/restore missing')
    kernel=bytearray(orig)
    kernel[start:start+len(payload)]=payload
    for i,(_,site,opcode) in enumerate(SITES):
        struct.pack_into('<I',kernel,off(kernel,site),branch(site,CAVE+i*28))
    allowed=set(range(start,start+len(payload)))
    for _,site,_ in SITES:allowed.update(range(off(kernel,site),off(kernel,site)+4))
    diffs=[i for i,(x,y) in enumerate(zip(orig,kernel)) if x!=y]
    if not diffs or any(i not in allowed for i in diffs):raise ValueError('Changed native code outside approved stubs')
    result=bytearray(boot)
    for i in diffs:result[MACHO_OFF+i]=kernel[i]
    if sha(result)!=OUTPUT_BOOT or sha(kernel)!=OUTPUT_MACHO:
        raise ValueError('SHA-256 mismatch against independently assembled image')
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(result)
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps({'variant':'flow-b','hardware_tested':False,
       'input_boot_sha256':SOURCE_BOOT,'output_boot_sha256':OUTPUT_BOOT,'output_macho_sha256':OUTPUT_MACHO,
       'payload_sha256':PAYLOAD_SHA,'payload_bytes':len(payload),'changed_kernel_bytes':len(diffs),
       '8_native_hook_sites':[{'stage':n,'va':hex(v),'replayed_opcode':hex(op)} for n,v,op in SITES],
       'x0_to_x18_and_x30_saved':True,'nzcv_saved':True,
       'extra_psci_calls':False,'additional_page_table_writes':False,
       'safety':'HIGH-RISK temporary fastboot boot ONLY; never flash'},indent=2)+'\n')
    print('FLOW-B',OUTPUT_BOOT,'changes',len(diffs))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

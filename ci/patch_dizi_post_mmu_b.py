#!/usr/bin/env python3
"""Dizi post-SCTLR two-checkpoint A/B on the exact orange-b boot-v4 image.

Y552 is after SCTLR_EL1+ISB; Y576 is after the native cmp/b.ne self-loop.
The XNU bootstrap uses V=P page tables. These framebuffer markers assume
0xB8000000 remains mapped after MMU enable; absence of either stripe is
NOT proof the CPU never reached the hook (mapping itself can fail).
Diagnostic only. Temporary fastboot boot ONLY. NEVER fastboot flash.
"""
from __future__ import annotations
import argparse, hashlib, json, struct
from pathlib import Path

SRC_BOOT_SHA = '1c245f4da986e6ea57f928246064939ddcdc44c4833535184fa78b60532e060e'
SRC_MACHO_SHA = '58ba8bb76ad326ea765a92299ef845e2fa574cbf94c181c5249e42da1250293e'
OUTPUT_BOOT_SHA = 'c79487a78c23db8eae9948b23dfc2f4953937dc93f89b67b2ec6bcd2a04e69af'
OUTPUT_MACHO_SHA = 'e08f5af65af91e1bbb2065806f392f32eae6166e56a20f5fefef7df741380cf1'
BOOT_SIZE = 68800512
KERNEL_OFFSET = 0x19c000 + 0x101200
KERNEL_SIZE = 51941376
ENTRY = 0xfffffff0073f0488
FRAMEBUFFER_PA = 0xb8000000
ROW_BYTES = 6400
STAGES = (
    ('AFTER_SCTLR_ISB', 0xfffffff0073f2358, 0xf2e00001, ENTRY+0x400, 552, 0xff00e5ff),
    ('AFTER_SCTLR_GUARD', 0xfffffff0073f2370, 0xd2a00600, ENTRY+0x430, 576, 0xffffe600),
)

def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def arm_b(src: int, dst: int) -> int:
    delta = dst-src
    if delta%4 or not -(1<<27)<=delta<(1<<27):
        raise ValueError('Out-of-range AArch64 branch')
    return 0x14000000 | ((delta>>2) & 0x3ffffff)

def offset(b: bytes, va: int) -> int:
    if len(b)<4096 or struct.unpack_from('<I',b)[0]!=0xfeedfacf:
        raise ValueError('Expected Mach-O64')
    n,length=struct.unpack_from('<II',b,16)
    if not 0<n<256 or length>len(b)-32:
        raise ValueError('Invalid Mach-O commands')
    p=32;end=p+length
    for _ in range(n):
        if p+8>end:raise ValueError('Truncated load commands')
        cmd,size=struct.unpack_from('<II',b,p)
        if size<8 or p+size>end:raise ValueError('Invalid load command size')
        if cmd==0x19:
            if size<72:raise ValueError('Bad LC_SEGMENT_64')
            name,addr,vs,off,fs=struct.unpack_from('<16sQQQQ',b,p+8)
            if name.rstrip(b'\0')==b'__TEXT_EXEC' and addr<=va<addr+min(vs,fs):
                dest=off+va-addr
                if dest<0 or dest+4>len(b):raise ValueError('Bad executable offset')
                return dest
        p+=size
    raise ValueError(f'No __TEXT_EXEC mapping for {va:#x}')

def marker(stub: int, hook: int, displaced: int, y: int, color: int) -> bytes:
    pa=FRAMEBUFFER_PA + y*ROW_BYTES
    if y<0 or y+9>2560 or pa+9*ROW_BYTES>FRAMEBUFFER_PA+2560*ROW_BYTES:
        raise ValueError('Invalid GOP stripe coordinates')
    # Instruction encodings independently compared with clang/llvm-objdump.
    words=[0xd2800009|((pa&0xffff)<<5),
           0xf2a00009|(((pa>>16)&0xffff)<<5),
           0x5280000a|((color&0xffff)<<5),
           0x72a0000a|(((color>>16)&0xffff)<<5),
           0x5283840b, 0x2881292a, 0x5100056b, 0x35ffffcb,
           0xd5033f9f, displaced, arm_b(stub+40,hook+4)]
    return struct.pack('<11I',*words)

def build(src: Path, dst: Path, report: Path) -> dict:
    if src.resolve()==dst.resolve():raise ValueError('Refusing to overwrite source')
    boot=src.read_bytes()
    if len(boot)!=BOOT_SIZE or sha(boot)!=SRC_BOOT_SHA:
        raise ValueError('Not the immutable orange-b boot image')
    if boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4:
        raise ValueError('Expected Android boot v4')
    fat=memoryview(boot)[0x19c000:0x19c000+64*1024*1024]
    if fat[82:87].tobytes()!=b'FAT32':raise ValueError('FAT32 missing')
    geometry=(struct.unpack_from('<H',fat,11)[0],fat[13],
              struct.unpack_from('<H',fat,14)[0],fat[16],
              struct.unpack_from('<I',fat,36)[0],struct.unpack_from('<I',fat,44)[0])
    if geometry!=(512,1,32,2,1009,2):raise ValueError('FAT32 geometry mismatch')
    orig=bytearray(boot[KERNEL_OFFSET:KERNEL_OFFSET+KERNEL_SIZE])
    if len(orig)!=KERNEL_SIZE or sha(orig)!=SRC_MACHO_SHA:
        raise ValueError('Not the exact orange-b Mach-O')
    new=bytearray(orig)
    if struct.unpack_from('<II',orig,offset(orig,0xfffffff0073f2350))!=(0xd5181000,0xd5033fdf):
        raise ValueError('SCTLR_EL1 and ISB modified')
    if (struct.unpack_from('<I',orig,offset(orig,0xfffffff0073f2368))[0]!=0xeb01001f or
        struct.unpack_from('<I',orig,offset(orig,0xfffffff0073f236c))[0]!=0x54000001):
        raise ValueError('Missing native SCTLR guard cmp / b.ne self-loop')
    if struct.unpack_from('<I',orig,offset(orig,0xfffffff0073f234c))[0]!=arm_b(0xfffffff0073f234c,ENTRY+0xc0):
        raise ValueError('Expected confirmed orange-b diagnostic')
    if struct.unpack_from('<I',orig,offset(orig,ENTRY+0x3a4))[0]!=0xd2920009:
        raise ValueError('Expected sixth no-SP marker')
    touched=set();items=[]
    for name,site,displaced,stub,y,color in STAGES:
        at=offset(orig,site);cave=offset(orig,stub)
        if struct.unpack_from('<I',orig,at)[0]!=displaced:
            raise ValueError('Unexpected original word at '+name)
        if any(orig[cave:cave+44]):
            raise ValueError('Nonempty code cave at '+name)
        code=marker(stub,site,displaced,y,color)
        new[cave:cave+44]=code
        struct.pack_into('<I',new,at,arm_b(site,stub))
        touched.update(range(cave,cave+44));touched.update(range(at,at+4))
        items.append({'name':name,'hook':hex(site),'cave':hex(stub),'gop_y':[y,y+8],
                      'color':hex(color),'displaced':hex(displaced)})
    changes=[i for i,(a,b) in enumerate(zip(orig,new)) if a!=b]
    if not changes or any(i not in touched for i in changes):
        raise AssertionError('Unexpected patch escape')
    if struct.unpack_from('<II',new,offset(new,0xfffffff0073f2350))!=(0xd5181000,0xd5033fdf):
        raise AssertionError('SCTLR/ISB changed')
    result=bytearray(boot)
    for idx in changes:result[KERNEL_OFFSET+idx]=new[idx]
    new_sha=sha(result);new_macho_sha=sha(new)
    if new_sha!=OUTPUT_BOOT_SHA or new_macho_sha!=OUTPUT_MACHO_SHA:
        raise ValueError('Output hashes differ from pinned local build: '+new_sha+' / '+new_macho_sha)
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_bytes(result)
    meta={'marker':'DIZI_POST_SCTLR_VP_GOP_AB_V1',
          'source_boot_sha256':SRC_BOOT_SHA,'source_macho_sha256':SRC_MACHO_SHA,
          'output_boot_sha256':new_sha,'output_macho_sha256':new_macho_sha,
          'changed_macho_bytes':len(changes),'stages':items,
          'original_sctlr_isb_cmp_guard_preserved':True,
          'working_edk2_fat_boot_header_untouched':True,
          'cpu_mmu_boot_confirmed':False,
          'limitation':'Y552 visible implies post-SCTLR+ISB execution AND V=P GOP mapping; missing Y552 can also be a mapping issue. Y576 means the original b.ne-self guard was passed.',
          'safety':'High risk. Temporary fastboot boot ONLY. NEVER flash.'}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2))
    return meta

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args()
    build(args.input,args.output,args.report)

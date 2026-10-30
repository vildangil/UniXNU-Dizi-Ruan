#!/usr/bin/env python3
"""SHA-pinned Dizi XNU alias-b: ONE guarded TTBR1 Device framebuffer block.

Early pre-SCTLR hook verifies the hardware-observed TCR, TTBR1, VBAR,
MAIR, disabled old MMU, existing L1/code-L2 and empty alias-L2 slot.
Only then it installs an XN, privileged Device-nGnRnE 2-MiB mapping
and performs DSB/TLBI/ISB. Two independent post-SCTLR text checkpoints
use the HIGH VIRTUAL alias, not raw framebuffer PA.

EXPERIMENTAL AND HIGH RISK; temporary fastboot boot only. NEVER flash.
No claim of XNU/OS boot success.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_BOOT_SHA = 'ab1edbbc8b05fe9b59f0f6909ce84c75faf40c1c98edea6acb50d268c9e688ee'
BASE_MACHO_SHA = '9e0f5f1411d674879ceedad09736e941349d487bb4836949e8a3bc51c4289662'
OUTPUT_BOOT_SHA = 'ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd'
OUTPUT_MACHO_SHA = '991a06e89c1d75eccd0c82f7efc28127d877b8318178c343225cb3c34a341876'
FONT_SHA = '71d8475b427a59edaca1ad55592e83812e7fe5c7f8be8444ffc1d3733d303501'
BOOT_SIZE = 68800512
KERNEL_OFFSET = 0x19c000 + 0x101200
KERNEL_SIZE = 51941376
ENTRY = 0xfffffff0073f0488
CAVE = ENTRY + 0x500
CAVE_END = ENTRY + 0xb30
FIRST = 0xfffffff0073f205c
PRE = 0xfffffff0073f234c
SCTLR = PRE + 4
POST = 0xfffffff0073f2358
GUARD = 0xfffffff0073f2370
VECTOR_START = 0xfffffff0073f1000
FB_PA = 0xb8000000
FB_ALIAS_VA = 0xfffffff004000000
BLOCK_DESC = 0x00600000b8000c0d
SYMBOLS = ('dizi_entry_trampoline','dizi_pre_trampoline',
           'dizi_post_trampoline','dizi_guard_trampoline',
           'entry_resume','pre_resume','post_resume','guard_resume')


def sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def branch(src: int, dst: int) -> int:
    delta = dst - src
    if delta % 4 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError('AArch64 direct branch out of range')
    return 0x14000000 | ((delta >> 2) & 0x3ffffff)


def code_offset(macho: bytes, va: int) -> int:
    if len(macho)<4096 or struct.unpack_from('<I',macho)[0]!=0xfeedfacf:
        raise ValueError('Expected Mach-O64')
    n,size = struct.unpack_from('<II',macho,16)
    if not 0<n<256 or size>len(macho)-32:
        raise ValueError('Invalid Mach-O command count/size')
    p,end=32,32+size
    for _ in range(n):
        if p+8>end:
            raise ValueError('Truncated Mach-O load command')
        cmd,length=struct.unpack_from('<II',macho,p)
        if length<8 or p+length>end:
            raise ValueError('Invalid Mach-O load command')
        if cmd==0x19:
            name,base,virtual_size,fileoff,filesize=struct.unpack_from('<16sQQQQ',macho,p+8)
            if name.rstrip(b'\0')==b'__TEXT_EXEC' and base<=va<base+min(virtual_size,filesize):
                result=fileoff+va-base
                if result+4>len(macho):
                    raise ValueError('Out-of-bounds executable file offset')
                return result
        p+=length
    raise ValueError('VA outside Mach-O __TEXT_EXEC: '+hex(va))


def compile_trace(macho: bytes) -> tuple[bytes, dict[str,int]]:
    start=code_offset(macho,CAVE)
    font=macho[start+700:start+1113]
    if len(font)!=413 or sha(font)!=FONT_SHA:
        raise ValueError('Previously hardware-tested 5x7 font mismatch')
    source=(HERE/'dizi_mmu_alias_b.S.in').read_text()
    if source.count('FONT_DATA')!=1:
        raise ValueError('Assembly source font placeholder changed')
    source=source.replace('FONT_DATA','.byte '+','.join(str(x) for x in font))
    clang=shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    if not clang or not objcopy or not shutil.which('readelf') or not shutil.which('nm'):
        raise RuntimeError('clang, llvm-objcopy, readelf, and nm required')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)
        (p/'trace.S').write_text(source)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(p/'trace.S'),'-o',str(p/'trace.o')],check=True)
        reloc=subprocess.check_output(['readelf','-r',str(p/'trace.o')],text=True)
        if 'There are no relocations in this file' not in reloc:
            raise ValueError('Unresolved ARM64 relocation(s): '+reloc)
        symbols={}
        for line in subprocess.check_output(['nm','-n',str(p/'trace.o')],text=True).splitlines():
            fields=line.split()
            if len(fields)==3 and fields[2] in SYMBOLS:
                symbols[fields[2]]=int(fields[0],16)
        if len(symbols)!=len(SYMBOLS):
            raise ValueError('Missing tracer label(s): '+str(symbols))
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(p/'trace.o'),str(p/'trace.bin')],check=True)
        data=bytearray((p/'trace.bin').read_bytes())
    if CAVE+len(data)>=VECTOR_START or len(data)>CAVE_END-CAVE:
        raise ValueError('Code overlaps exception vectors / tracer cave')
    for symbol,target in (('entry_resume',FIRST),('pre_resume',SCTLR),
                          ('post_resume',POST+4),('guard_resume',GUARD+4)):
        pos=symbols[symbol]
        if struct.unpack_from('<I',data,pos)[0]!=0xd503201f:
            raise ValueError('Expected NOP at return label: '+symbol)
        struct.pack_into('<I',data,pos,branch(CAVE+pos,target))
    for label,displaced in (('dizi_pre_trampoline',0xf28b27a0),
                            ('dizi_post_trampoline',0xf2e00001),
                            ('dizi_guard_trampoline',0xd2a00600)):
        if struct.unpack_from('<I',data,symbols[label])[0]!=displaced:
            raise ValueError('Native displaced opcode not replayed')
    if ((FB_ALIAS_VA>>30)&0xff)!=0xc0 or ((FB_ALIAS_VA>>21)&511)!=0x20:
        raise ValueError('Not the tested high alias L1 C0/L2 20')
    if (BLOCK_DESC&3)!=1 or ((BLOCK_DESC>>2)&7)!=3:
        raise ValueError('Not a Device type L2 block descriptor')
    if (BLOCK_DESC & 0x0000ffffffe00000)!=FB_PA:
        raise ValueError('Framebuffer block PA mismatch')
    if not all(BLOCK_DESC & (1<<bit) for bit in (10,11,53,54)):
        raise ValueError('Descriptor lacks AF/nG/PXN/UXN')
    for msg,y in (('DIZI XNU ENTRY',64),('PRE ALIAS ARMED',110),
                  ('ALIAS GUARD FAIL',110),('POST SCTLR OK',170),('GUARD PASSED',230)):
        # 4x glyph: each character advances 96 bytes, 7 glyph rows * 4 scanlines.
        if y*6400+160+(len(msg)-1)*96+20*4+28*6400 >= 2*1024*1024:
            raise ValueError('Post-MMU renderer crosses first 2-MiB alias')
    return bytes(data),symbols


def build(source: Path, destination: Path, report: Path) -> dict:
    if source.resolve()==destination.resolve():
        raise ValueError('Refusing in-place modification')
    boot=source.read_bytes()
    if (len(boot)!=BOOT_SIZE or sha(boot)!=BASE_BOOT_SHA or
        boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4):
        raise ValueError('Source is not SHA-pinned slot-b Android boot-v4 image')
    fat=memoryview(boot)[0x19c000:0x19c000+64*1024*1024]
    if fat[82:87].tobytes()!=b'FAT32':
        raise ValueError('Expected existing FAT32')
    original=boot[KERNEL_OFFSET:KERNEL_OFFSET+KERNEL_SIZE]
    if sha(original)!=BASE_MACHO_SHA:
        raise ValueError('Unexpected source Mach-O SHA-256')
    k=bytearray(original)
    offset=lambda va:code_offset(k,va)
    if struct.unpack_from('<II',k,offset(SCTLR))!=(0xd5181000,0xd5033fdf):
        raise ValueError('Original SCTLR_EL1/ISB changed')
    if struct.unpack_from('<II',k,offset(0xfffffff0073f2368))!=(0xeb01001f,0x54000001):
        raise ValueError('Original CMP/B.NE self-guard changed')
    if struct.unpack_from('<I',k,offset(ENTRY))[0]!=branch(ENTRY,CAVE):
        raise ValueError('Known entry hook absent')
    if struct.unpack_from('<I',k,offset(PRE))[0]!=branch(PRE,CAVE+16):
        raise ValueError('Known pre-SCTLR hook absent')
    if struct.unpack_from('<I',k,offset(POST))[0]!=0xf2e00001 or struct.unpack_from('<I',k,offset(GUARD))[0]!=0xd2a00600:
        raise ValueError('Expected uninstrumented post-SCTLR opcodes')
    code,symbols=compile_trace(k)
    start,end=offset(CAVE),offset(CAVE_END)
    if end-start!=1584:
        raise ValueError('Wrong code-cave geometry')
    k[start:end]=bytes(end-start)
    k[start:start+len(code)]=code
    for site,label in ((ENTRY,'dizi_entry_trampoline'),(PRE,'dizi_pre_trampoline'),
                       (POST,'dizi_post_trampoline'),(GUARD,'dizi_guard_trampoline')):
        struct.pack_into('<I',k,offset(site),branch(site,CAVE+symbols[label]))
    editable=set(range(start,end))
    for site in (ENTRY,PRE,POST,GUARD):
        editable.update(range(offset(site),offset(site)+4))
    changed=[i for i,(a,b) in enumerate(zip(original,k)) if a!=b]
    if not changed or any(i not in editable for i in changed):
        raise ValueError('Patched outside known diagnostic cave and hooks')
    if struct.unpack_from('<II',k,offset(SCTLR))!=(0xd5181000,0xd5033fdf) or struct.unpack_from('<II',k,offset(0xfffffff0073f2368))!=(0xeb01001f,0x54000001):
        raise ValueError('Native SCTLR/ISB or guard accidentally patched')
    result=bytearray(boot)
    for i in changed:result[KERNEL_OFFSET+i]=k[i]
    boot_sha,macho_sha=sha(result),sha(k)
    if boot_sha!=OUTPUT_BOOT_SHA or macho_sha!=OUTPUT_MACHO_SHA:
        raise ValueError('Output differs from independently verified image: '+boot_sha+' / '+macho_sha)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(result)
    metadata={
      'variant':'alias-b',
      'input_boot_sha256':BASE_BOOT_SHA,
      'input_macho_sha256':BASE_MACHO_SHA,
      'output_boot_sha256':boot_sha,
      'output_macho_sha256':macho_sha,
      'arm64_stub_bytes':len(code),
      'changed_macho_bytes':len(changed),
      'framebuffer_pa':hex(FB_PA),
      'high_virtual_alias':hex(FB_ALIAS_VA),
      'page_table_l1_index':'C0','page_table_l2_index':'20',
      'l2_block_descriptor':hex(BLOCK_DESC),
      'device_mair_attribute_index':3,
      'expected_mair_el1':'0x0C0804FF00BB44FF',
      'correction':'One ARM64 MOVK immediate changed from 0x008b to 0x00bb; matching measured MAIR_EL1.',
      'pre_sctlr_guards':['TCR','TTBR1','VBAR','MAIR','SCTLR.M=0',
                          'verified L1 table','verified executable L2 block',
                          'empty L2 alias slot'],
      'post_isb_text':'POST SCTLR OK',
      'post_native_compare_text':'GUARD PASSED',
      'original_sctlr_isb_cmp_bne_unchanged':True,
      'post_mmu_fb_writes_use_verified_t1_alias_only':True,
      'first_2_mib_only':True,
      'hardware_tested':False,
      'safety':'HIGH RISK. Temporary fastboot boot ONLY, NEVER flash.'
    }
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata,indent=2))
    return metadata


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    opts=parser.parse_args()
    build(opts.input,opts.output,opts.report)

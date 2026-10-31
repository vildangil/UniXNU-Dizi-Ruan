#!/usr/bin/env python3
"""Guards and transfers one 2-MiB Device framebuffer mapping before XNU TTBR1 replacement.

ONLY the SHA-pinned physical STACK-B baseline is accepted. This is an
experimental diagnostic, not a general framebuffer/VM/driver implementation.
Guard failures intentionally stop BEFORE the native TTBR switch. The post-switch
checkpoint is AFTER native TLBI/DSB/ISB and requires the expected TTBR1 root.
Temporary fastboot boot ONLY, NEVER flash an Android partition.
"""
from __future__ import annotations
import argparse,hashlib,json,struct,subprocess,tempfile,shutil
from pathlib import Path

INPUT_BOOT='0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed'
INPUT_MACHO='396b1c94f6024efbd534957ea9fc6708ab1178997d2ae7fcf6ba61d3afc59f3d'
OUTPUT_BOOT='4ff3a8f6839bc3ba9f33a91356b9f55e4e8cd65d6fafaf30391ba41e5babd195'
OUTPUT_MACHO='4ea7271ea3aefcd741dab55fff5f2f4bbfbec0252c38176da1038ca9cd3f2c3c'
TRACE_SHA='1ad661288c843dab1bb6f5f1aa9567763da9d5aad1c8bf7801c359b391793379'
FONT_SHA='71d8475b427a59edaca1ad55592e83812e7fe5c7f8be8444ffc1d3733d303501'
BOOT_BYTES=68800512
MACHO_OFF=0x29d200
MACHO_LEN=51941376
CAVE=0xfffffff0073f1800
CAVE_SIZE=2032
PRE=0xfffffff0073ea0b0
POST=0xfffffff0073ea130
OLD_HOOKS=[(0xfffffff0073e95dc,0xaa0103fa),
           (0xfffffff0073e97f8,0xf0ffec08),
           (0xfffffff0073ea104,0xf9400108),
           (PRE,0xd0ffec08)]
EXPECTED_MMU=(0x9240bd00,0x94003041,0xd508831f,0xd5033b9f,0xd5033fdf)
GUARDS={1:'TCR exact 4KiB/38bit/40bit',2:'MAIR exact (AttrIdx 3 Device)',
        3:'SCTLR.M enabled',4:'old TTBR1 root unchanged',
        5:'future root PA and native VA match physical evidence',
        6:'future L1[C0] next-table descriptor match',
        7:'native phystokv future child VA match',
        8:'future FB L2[20] zero and code L2[39] intact',
        9:'native old L2 FB descriptor matches before copy/readback'}
sha=lambda b:hashlib.sha256(b).hexdigest()

def off(k:bytes,va:int)->int:
    if struct.unpack_from('<I',k)[0]!=0xfeedfacf:raise ValueError('Need Mach-O64')
    n,cmdbytes=struct.unpack_from('<II',k,16)
    if not 0<n<256 or cmdbytes>len(k)-32:raise ValueError('Bad load commands')
    cursor=32
    for _ in range(n):
        cmd,size=struct.unpack_from('<II',k,cursor)
        if size<8 or cursor+size>32+cmdbytes:raise ValueError('Bad load-command extent')
        if cmd==0x19:
            name,base,vsize,fo,fs=struct.unpack_from('<16sQQQQ',k,cursor+8)
            if name.rstrip(b'\0')==b'__TEXT_EXEC' and base<=va<base+min(fs,vsize):
                return int(fo+va-base)
        cursor+=size
    raise ValueError('VA not inside __TEXT_EXEC '+hex(va))

def branch(src:int,dst:int)->int:
    delta=dst-src
    if delta%4 or not -(1<<27)<=delta<(1<<27):raise ValueError('Branch range')
    return 0x14000000 | ((delta>>2)&0x3ffffff)

def adrp(src:int,dst:int,rd:int)->int:
    delta=(dst>>12)-(src>>12)
    if not -(1<<20)<=delta<(1<<20):raise ValueError('ADRP out of range')
    imm=delta&0x1fffff
    return 0x90000000|((imm&3)<<29)|((imm>>2)<<5)|rd

def build(source:Path,outfile:Path,report:Path)->None:
    if source.resolve()==outfile.resolve():raise ValueError('Cannot overwrite input')
    boot=source.read_bytes()
    if len(boot)!=BOOT_BYTES or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4 or sha(boot)!=INPUT_BOOT:
        raise ValueError('Expected exact hardware-tested STACK-B boot-v4')
    original=boot[MACHO_OFF:MACHO_OFF+MACHO_LEN]
    if sha(original)!=INPUT_MACHO:raise ValueError('Unexpected STACK-B Mach-O')
    k=bytearray(original)
    start=off(k,CAVE);end=start+CAVE_SIZE
    font=next((original[start+i:start+i+413] for i in range(CAVE_SIZE-412)
               if sha(original[start+i:start+i+413])==FONT_SHA),None)
    if font is None:raise ValueError('Original 413-byte reviewed font not found')
    for va,opcode in OLD_HOOKS:
        old=struct.unpack_from('<I',k,off(k,va))[0]
        delta=((old&0x3ffffff)^0x2000000)-0x2000000
        if old>>26!=0x5 or not CAVE<=va+delta*4<CAVE+CAVE_SIZE:
            raise ValueError('Unexpected STACK-B hook '+hex(va))
        struct.pack_into('<I',k,off(k,va),opcode)
    if struct.unpack_from('<I',k,off(k,POST))[0]!=0xd0ffec08:
        raise ValueError('Post-switch ADRP changed')
    if struct.unpack_from('<5I',k,off(k,0xfffffff0073ea11c))!=EXPECTED_MMU:
        raise ValueError('Native TTBR/ISB/barrier instruction changed')
    asm=Path(__file__).with_name('dizi_mmu_fb_bridge_b.S.in').read_text()
    replacements={
      'HOOK_PRE_ADRP':hex(adrp(CAVE+20,0xfffffff00716c000,8)),
      'HOOK_PRE_RETURN':hex(branch(CAVE+24,PRE+4)),
      'HOOK_POST_ADRP':hex(adrp(CAVE+48,0xfffffff00716c000,8)),
      'HOOK_POST_RETURN':hex(branch(CAVE+52,POST+4)),
      'FONT_DATA':'.byte '+','.join(map(str,font))
    }
    for token,replacement in replacements.items():
        if asm.count(token)!=1:raise ValueError('Template token changed: '+token)
        asm=asm.replace(token,replacement)
    clang=shutil.which('clang-19') or shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-19') or shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    readelf=shutil.which('readelf')
    if not clang or not objcopy or not readelf:raise RuntimeError('clang, llvm-objcopy and readelf required')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)
        (p/'trace.S').write_text(asm)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(p/'trace.S'),'-o',str(p/'trace.o')],check=True)
        reloc=subprocess.check_output([readelf,'-r',str(p/'trace.o')],text=True)
        if 'There are no relocations in this file' not in reloc:
            raise ValueError('Unresolved relocations in diagnostic code')
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(p/'trace.o'),str(p/'trace.bin')],check=True)
        payload=(p/'trace.bin').read_bytes()
    if len(payload)!=1463 or sha(payload)!=TRACE_SHA or len(payload)>CAVE_SIZE:
        raise ValueError('Tracer differs from independently compiled source')
    # Limits: font is 59 chars (ASCII 32..90), all labels upper case + digits.
    # Character coverage for first 2 MiB: two 28px tall rows at y184 and y218.
    if (218+28)*6400 + 80+len('FB NEW TTBR OK')*96 >= 2*1024*1024:
        raise ValueError('Renderer exceeds existing 2MiB high VA framebuffer alias')
    k[start:end]=bytes(CAVE_SIZE)
    k[start:start+len(payload)]=payload
    for site,delta in [(PRE,0),(POST,28)]:
        struct.pack_into('<I',k,off(k,site),branch(site,CAVE+delta))
    allowed=set(range(start,end))
    for site,_ in OLD_HOOKS:
        allowed.update(range(off(k,site),off(k,site)+4))
    allowed.update(range(off(k,POST),off(k,POST)+4))
    changed=[i for i,(a,b) in enumerate(zip(original,k)) if a!=b]
    if not changed or any(i not in allowed for i in changed):raise ValueError('Modifications escaped tracer cave/hooks')
    result=bytearray(boot)
    result[MACHO_OFF:MACHO_OFF+MACHO_LEN]=k
    bh,mh=sha(result),sha(k)
    if bh!=OUTPUT_BOOT or mh!=OUTPUT_MACHO:
        raise ValueError('Reproducibility mismatch: '+bh+' / '+mh)
    outfile.parent.mkdir(parents=True,exist_ok=True);outfile.write_bytes(result)
    record={'variant':'fb-bridge-b','source_variant':'stack-b','hardware_tested':False,
            'input_boot_sha256':INPUT_BOOT,'output_boot_sha256':bh,
            'output_macho_sha256':mh,'tracer_sha256':TRACE_SHA,
            'tracer_bytes':len(payload),'changed_kernel_bytes':len(changed),
            'new_table_writes':'ONE exact future TTBR1 L2[0x20] 2MiB Device block at physical 0x804192100, only after all guards',
            'guards':GUARDS,'pre_switch':'FB ALIAS READY or FBFAIL1..FBFAIL9 and intentional stop',
            'post_switch':'FB NEW TTBR OK after native TTBR1/TTBR0 writes + TLBI/DSB/ISB',
            'native_mmu_opcodes_unchanged':True,'psci_cpu_on':False,'new_gic_mmio':False,
            'error_policy':'Fail-closed WFE loop before native switch; never post-write framebuffer under unverified TTBR1',
            'safety':'HIGH RISK. Temporary fastboot boot only. NEVER fastboot flash.'}
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('input','output','report'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args()
    build(args.input,args.output,args.report)

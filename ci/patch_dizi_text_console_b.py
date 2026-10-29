#!/usr/bin/env python3
"""SHA-pinned dizi XNU text console replacing 16 legacy framebuffer stripes.

Restores original early XNU opcodes (including PC-relative ADRPs), draws
large text at Mach-O entry and immediately before SCTLR_EL1. Stackless,
NZCV-neutral and no framebuffer access after enabling MMU. It does NOT
claim MMU or full XNU boot. Temporary fastboot boot only; never flash.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, struct, subprocess, tempfile
from pathlib import Path
import patch_dizi_post_mmu_b as core

ENTRY=core.ENTRY
FIRST=0xfffffff0073f205c
PRE=0xfffffff0073f234c
SCTLR=PRE+4
CAVE=ENTRY+0x1300
LIMIT=ENTRY+0x1b30
BASE_SHA=core.OUTPUT_BOOT_SHA
BASE_MACHO_SHA=core.OUTPUT_MACHO_SHA
OUTPUT_SHA='feaa33629f5830f2545b6d097e91438694029e8347badb89e243d7dda3dd4423'
OUTPUT_MACHO_SHA='5f36cafc84f1404dd1b6abc3e36f19b6def04d950f46ba2affc5c1425b956122'
FONT_HEX=('000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001f00000000000000000404010102040810100e11131519110e040c040404040e0e11010204081f1e01010e01011e02060a121f02021f10101e01011e0e10101e11110e1f0102040808080e11110e11110e0e11110f01010e00040400040400000000000000000000000000000000000000000000100804020408100e110102040004000000000000000e11111f1111111e11111e11111e0f10101010100f1e11111111111e1f10101e10101f1f10101e1010100f10101711110f1111111f1111111f04040404041f0702020212120c111214181412111010101010101f111b1515111111111915131111110e11111111110e1e11111e1010100e11111115120d1e11111e1412110f10100e01011e1f0404040404041111111111110e11111111110a041111111515150a11110a040a111111110a040404041f01020408101f')
ENTRY_TEXT=('DIZI / XNU DEBUG','STATE: XNU ENTRY','PASS: DARWIN HANDOFF','NEXT: BOOTARGS / MMU','MODE: SINGLE CPU','WAIT: NATIVE BOOTSTRAP')
PRE_TEXT=('DIZI / XNU DEBUG','PASS: XNU ENTRY','PASS: BOOTARGS / TTB','PASS: TTBR1 MAIR TLBI VBAR','NOW: PRE SCTLR EL1','MMU ON: NOT VERIFIED','POST MMU: NOT PROBED')
# (original instruction VA, original opcode, old relocated tracer VA)
RESTORE=(
 (FIRST,0xd510109f,ENTRY+0x80),
 (0xfffffff0073f2078,0xf9400696,ENTRY+0x120),
 (0xfffffff0073f208c,0xd51bd07f,ENTRY+0x14c),
 (0xfffffff0073f20f0,0xd0ffe080,ENTRY+0x178), # original ADRP PC-relative
 (0xfffffff0073f2290,0x90ffebc0,ENTRY+0x1a4), # original ADRP PC-relative
 (0xfffffff0073f22ac,0xaa1303fe,ENTRY+0x1d0),
 (0xfffffff0073f22b4,0x9240bc00,ENTRY+0x200),
 (0xfffffff0073f22bc,0xaa1f03e0,ENTRY+0x254),
 (0xfffffff0073f22fc,0xaa010000,ENTRY+0x2a8),
 (0xfffffff0073f2308,0xd508871f,ENTRY+0x2fc),
 (0xfffffff0073f2330,0x91000000,ENTRY+0x350),
 (0xfffffff0073f2340,0xf2e00000,ENTRY+0x3a4),
 (0xfffffff0073f2358,0xf2e00001,ENTRY+0x400),
 (0xfffffff0073f2370,0xd2a00600,ENTRY+0x430),
)
ASM=r'''
.section .text.trace,"ax",%progbits
.p2align 2
.global dizi_entry_trampoline
.global dizi_sctlr_trampoline
.global dizi_renderer
dizi_entry_trampoline:
    adr x12, entry_resume
    mov w13, #0
    b .Lrenderer
entry_resume:
    nop
dizi_sctlr_trampoline:
    .inst 0xf28b27a0
    adr x12, sctlr_resume
    mov w13, #1
    b .Lrenderer
sctlr_resume:
    nop
dizi_renderer:
.Lrenderer:
    cbz w13, choose_entry
    adr x14, stage_sctlr
    b messages_selected
choose_entry:
    adr x14, stage_entry
messages_selected:
    movz x9, #0
    movk x9, #0xb800, lsl #16
    movz w10, #0x1324
    movk w10, #0xff0c, lsl #16
    movz x11, #0x4000
    movk x11, #0x001f, lsl #16
clear_loop:
    stp w10, w10, [x9], #8
    sub x11, x11, #1
    cbnz x11, clear_loop
    dsb sy
    movz w10, #0xf0ff
    movk w10, #0xffe6, lsl #16
    movz x13, #0x0000
    movk x13, #0xb800, lsl #16
    movz x9, #0xa740
    movk x9, #0x000e, lsl #16
    add x13, x13, x9
    mov x7, x13
    adr x16, font5_table
    movz x2, #0x9600
    movz x3, #6400
next_char:
    ldrb w9, [x14], #1
    cbz w9, renderer_done
    sub w8, w9, #10
    cbz w8, next_line
    sub w8, w9, #32
    lsl x5, x8, #3
    sub x5, x5, x8
    add x5, x16, x5
    mov x15, x7
    movz x11, #7
next_glyph_row:
    ldrb w9, [x5], #1
    mov x17, x15
    movz x8, #5
next_glyph_bit:
    tbz w9, #4, glyph_bit_blank
    mov x6, x17
    movz x4, #6
pixel_rows:
    stp w10, w10, [x6]
    stp w10, w10, [x6, #8]
    stp w10, w10, [x6, #16]
    add x6, x6, x3
    sub x4, x4, #1
    cbnz x4, pixel_rows
glyph_bit_blank:
    add x17, x17, #24
    lsl w9, w9, #1
    sub x8, x8, #1
    cbnz x8, next_glyph_bit
    add x15, x15, x2
    sub x11, x11, #1
    cbnz x11, next_glyph_row
    add x7, x7, #144
    b next_char
next_line:
    movz x9, #0xd600
    movk x9, #0x0006, lsl #16
    add x13, x13, x9
    mov x7, x13
    b next_char
renderer_done:
    dsb sy
    br x12
.p2align 2
font5_table:
FONT_DATA
.p2align 2
MESSAGE_DATA
'''

def sha(blob:bytes)->str:return hashlib.sha256(blob).hexdigest()

def asm_blob():
    font=bytes.fromhex(FONT_HEX)
    assert len(font)==59*7
    for texts in (ENTRY_TEXT,PRE_TEXT):
        for c in '\n'.join(texts):
            if c!='\n' and not (32<=ord(c)<=90):raise ValueError('Unsupported text glyph')
    blocks=['stage_entry','stage_sctlr']
    suffix=[]
    for sym,texts in zip(blocks,(ENTRY_TEXT,PRE_TEXT)):
        b='\n'.join(texts).encode('ascii')+b'\0'
        suffix.append(sym+':\n.byte '+','.join(str(x) for x in b))
    asm=ASM.replace('FONT_DATA','.byte '+','.join(str(x) for x in font)).replace('MESSAGE_DATA','\n'.join(suffix))
    clang=shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    if not clang or not objcopy or not shutil.which('readelf') or not shutil.which('nm'):
        raise RuntimeError('clang, llvm-objcopy, readelf and nm required')
    with tempfile.TemporaryDirectory() as t:
        p=Path(t);(p/'trace.S').write_text(asm)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(p/'trace.S'),'-o',str(p/'trace.o')],check=True)
        reloc=subprocess.check_output(['readelf','-r',str(p/'trace.o')],text=True)
        if 'There are no relocations' not in reloc:raise ValueError('Unresolved relocations: '+reloc)
        symbols={}
        for line in subprocess.check_output(['nm','-n',str(p/'trace.o')],text=True).splitlines():
            parts=line.split()
            if len(parts)==3 and parts[2] in {'dizi_entry_trampoline','dizi_sctlr_trampoline','entry_resume','sctlr_resume'}:
                symbols[parts[2]]=int(parts[0],16)
        if len(symbols)!=4:raise ValueError('Incomplete tracer symbols: '+str(symbols))
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(p/'trace.o'),str(p/'trace.bin')],check=True)
        blob=bytearray((p/'trace.bin').read_bytes())
    if len(blob)>LIMIT-CAVE:raise ValueError('Exceeds verified empty Mach-O cave')
    for resume,target in (('entry_resume',FIRST),('sctlr_resume',SCTLR)):
        i=symbols[resume]
        if struct.unpack_from('<I',blob,i)[0]!=0xd503201f:raise ValueError('Missing return NOP')
        struct.pack_into('<I',blob,i,core.arm_b(CAVE+i,target))
    return bytes(blob),symbols

def patch(source:Path,dest:Path,report:Path)->None:
    if source.resolve()==dest.resolve():raise ValueError('Cannot modify source in-place')
    boot=source.read_bytes()
    if len(boot)!=core.BOOT_SIZE or sha(boot)!=BASE_SHA or boot[:8]!=b'ANDROID!':raise ValueError('Not verified postmmu-b boot-v4')
    if struct.unpack_from('<I',boot,40)[0]!=4:raise ValueError('Expected boot v4')
    fat=memoryview(boot)[0x19c000:0x19c000+64*1024*1024]
    geo=(struct.unpack_from('<H',fat,11)[0],fat[13],struct.unpack_from('<H',fat,14)[0],fat[16],struct.unpack_from('<I',fat,36)[0],struct.unpack_from('<I',fat,44)[0])
    if fat[82:87].tobytes()!=b'FAT32' or geo!=(512,1,32,2,1009,2):raise ValueError('Wrong FAT geometry')
    old=boot[core.KERNEL_OFFSET:core.KERNEL_OFFSET+core.KERNEL_SIZE]
    if sha(old)!=BASE_MACHO_SHA:raise ValueError('Unexpected original Mach-O')
    k=bytearray(old)
    o=core.offset
    if struct.unpack_from('<II',k,o(k,SCTLR))!=(0xd5181000,0xd5033fdf):raise ValueError('SCTLR/ISB changed')
    if struct.unpack_from('<II',k,o(k,0xfffffff0073f2368))!=(0xeb01001f,0x54000001):raise ValueError('SCTLR compare/guard changed')
    if struct.unpack_from('<I',k,o(k,ENTRY))[0]!=core.arm_b(ENTRY,ENTRY+0x40):raise ValueError('No WHITE hook')
    if struct.unpack_from('<I',k,o(k,PRE))[0]!=core.arm_b(PRE,ENTRY+0xc0):raise ValueError('No ORANGE hook')
    for site,original,cave in RESTORE:
        if struct.unpack_from('<I',k,o(k,site))[0]!=core.arm_b(site,cave):raise ValueError(f'Stale tracer mismatch at {site:#x}')
        if original not in struct.unpack_from('<21I',k,o(k,cave)):
            raise ValueError('Displaced opcode absent at old cave')
        struct.pack_into('<I',k,o(k,site),original)
    blob,sym=asm_blob()
    start=o(k,CAVE);end=o(k,LIMIT)
    if any(k[start:end]):raise ValueError('Executable cave occupied; refusing overwrite')
    k[start:start+len(blob)]=blob
    struct.pack_into('<I',k,o(k,ENTRY),core.arm_b(ENTRY,CAVE+sym['dizi_entry_trampoline']))
    struct.pack_into('<I',k,o(k,PRE),core.arm_b(PRE,CAVE+sym['dizi_sctlr_trampoline']))
    ranges=[range(start,start+len(blob)),range(o(k,ENTRY),o(k,ENTRY)+4),range(o(k,PRE),o(k,PRE)+4)]
    ranges += [range(o(k,site),o(k,site)+4) for site,_,_ in RESTORE]
    allowed=set().union(*map(set,ranges))
    diffs=[i for i,(a,b) in enumerate(zip(old,k)) if a!=b]
    if not diffs or any(i not in allowed for i in diffs):raise ValueError('Edit escaped pinned tracers/cave')
    out=bytearray(boot)
    for i in diffs:out[core.KERNEL_OFFSET+i]=k[i]
    if sha(out)!=OUTPUT_SHA or sha(k)!=OUTPUT_MACHO_SHA:raise ValueError('Output differs from independent verified image')
    dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(out)
    meta={'marker':'DIZI_XNU_TEXT_B_V1','source_boot_sha256':BASE_SHA,'source_macho_sha256':BASE_MACHO_SHA,
          'output_boot_sha256':sha(out),'output_macho_sha256':sha(k),'changed_bytes':len(diffs),
          'previous_tracers_removed':len(RESTORE)+2,'text_stages':['XNU ENTRY','PRE SCTLR EL1'],
          'after_mmu_fb_writes':False,'native_sctlr_isb_guard_preserved':True,
          'edk2_fat_unchanged':True,'runtime_verified':False,
          'warning':'HIGH-RISK. Temporary fastboot boot only, NEVER flash. This is diagnostic, not XNU boot proof.'}
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();patch(a.input,a.output,a.report)

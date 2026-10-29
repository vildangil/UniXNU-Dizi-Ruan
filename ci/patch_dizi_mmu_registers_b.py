#!/usr/bin/env python3
"""SHA-pinned, stackless, pre-SCTLR register readout for dizi XNU.

Replace only the existing text-b tracer cave and two branch hooks. Do not
change EDK2, native MMU instructions or the original 14 restored XNU sites.
Physical framebuffer writes occur ONLY before SCTLR_EL1. Diagnostic only.
Temporary 'fastboot boot' ONLY; NEVER flash.
"""
from __future__ import annotations
import argparse,hashlib,json,shutil,struct,subprocess,tempfile
from pathlib import Path
import patch_dizi_text_console_b as textb
import patch_dizi_post_mmu_b as core

ENTRY=textb.ENTRY
FIRST=textb.FIRST
PRE=textb.PRE
SCTLR=textb.SCTLR
CAVE=textb.CAVE
LIMIT=textb.LIMIT
VECTOR_START=textb.VECTOR_START
BASE_BOOT_SHA=textb.OUTPUT_SHA
BASE_MACHO_SHA=textb.OUTPUT_MACHO_SHA
OUTPUT_BOOT_SHA='ccb3c22f680aa67aac58669f77c051e4784e253e7965baf3a93feb8e38374a0b'
OUTPUT_MACHO_SHA='a6222120639cc2fb39b5d3e353b623253d3cd9f58dd006685b95b8f1948f65eb'
# Display values captured by MRS at the actual pre-SCTLR trap, not constants.
# The pre-SCTLR SCTLR_EL1 is the OLD configuration. X22/X23 are bootstrap
# relocation intermediates; X25 is the candidate page-table buffer pointer.
REGS=(
 ('TCR','mrs x11, TCR_EL1'),
 ('TTBR1','mrs x11, TTBR1_EL1'),
 ('TTBR0','mrs x11, TTBR0_EL1'),
 ('MAIR','mrs x11, MAIR_EL1'),
 ('VBAR','mrs x11, VBAR_EL1'),
 ('SCTLR OLD','mrs x11, SCTLR_EL1'),
 ('X22','mov x11, x22'),
 ('X23','mov x11, x23'),
 ('X25 TTB','mov x11, x25'),
)

ASM=r'''
.section .text.trace,"ax",%progbits
.p2align 2
.global dizi_entry_trampoline
.global dizi_sctlr_trampoline
dizi_entry_trampoline:
    adr x12, entry_resume
    mov w13, #0
    b dizi_renderer
entry_resume:
    nop
dizi_sctlr_trampoline:
    .inst 0xf28b27a0    // native movk x0,#0x593d; x0 preserved afterward
    adr x12, sctlr_resume
    mov w13, #1
    b dizi_renderer
sctlr_resume:
    nop
dizi_renderer:
    cbz w13, choose_entry
    // Dynamic capture & 16-digit formatting writes ONLY inside this
    // private, already-empty Mach-O diagnostic cave, before MMU-on.
HEX_WRITES
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
    movz x13, #0
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
    stp w10, w10, [x6,#8]
    stp w10, w10, [x6,#16]
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
hex_digits:
.ascii "0123456789ABCDEF"
.p2align 2
MESSAGE_DATA
'''


def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()


def _byte_lines(label:str,blob:bytes)->str:
    return f'{label}:\n.byte '+','.join(str(c) for c in blob)


def assemble():
    font=bytes.fromhex(textb.FONT_HEX)
    if len(font)!=59*7:raise ValueError('Unexpected text-b font')
    entry_lines=('DIZI / XNU DEBUG','STATE: XNU ENTRY','PASS: DARWIN HANDOFF','NEXT: BOOTARGS / MMU','MODE: SINGLE CPU','WAIT: NATIVE BOOTSTRAP')
    pre_lines=['DIZI / XNU MMU REGS B','NOW: PRE SCTLR EL1']
    pre=[]
    pre.append(_byte_lines('stage_sctlr','\n'.join(pre_lines).encode('ascii')+b'\n'))
    for label,_ in REGS:
        ident=label.lower().replace(' ','_')
        pre.append('.byte '+','.join(map(str,(label+': ').encode('ascii'))))
        pre.append(f'hex_{ident}:\n.ascii "0000000000000000"')
        pre.append('.byte 10')
    pre.append('.byte '+','.join(map(str,b'MMU ON: NOT VERIFIED\nPOST MMU: NOT PROBED\0')))
    payload=_byte_lines('stage_entry','\n'.join(entry_lines).encode('ascii')+b'\0')+'\n'+'\n'.join(pre)
    hexcode=[]
    for idx,(label,instruction) in enumerate(REGS):
        ident=label.lower().replace(' ','_')
        loop=f'reg_hex_loop_{idx}'
        # No BL (which would clobber x30); no stack or NZCV changes.
        hexcode.extend((
          f'    adr x9, hex_{ident}',
          f'    {instruction}',
          '    adr x5, hex_digits',
          '    movz x6, #16',
          f'{loop}:',
          '    lsr x17, x11, #60',
          '    ldrb w17, [x5,x17]',
          '    strb w17, [x9], #1',
          '    lsl x11, x11, #4',
          '    sub x6, x6, #1',
          f'    cbnz x6, {loop}',
        ))
    asm=(ASM.replace('HEX_WRITES','\n'.join(hexcode))
          .replace('FONT_DATA','.byte '+','.join(str(c) for c in font))
          .replace('MESSAGE_DATA',payload))
    clang=shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    nm=shutil.which('nm')
    if not clang or not objcopy or not nm or not shutil.which('readelf'):
        raise RuntimeError('Need clang, llvm-objcopy, readelf, nm')
    with tempfile.TemporaryDirectory() as t:
        p=Path(t)
        (p/'trace.S').write_text(asm)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(p/'trace.S'),'-o',str(p/'trace.o')],check=True)
        reloc=subprocess.check_output(['readelf','-r',str(p/'trace.o')],text=True)
        if 'There are no relocations' not in reloc:
            raise ValueError('Unexpected ELF relocations: '+reloc)
        symbols={}
        for line in subprocess.check_output([nm,'-n',str(p/'trace.o')],text=True).splitlines():
            parts=line.split()
            if len(parts)==3 and (parts[2] in {'dizi_entry_trampoline','dizi_sctlr_trampoline','entry_resume','sctlr_resume'} or parts[2].startswith('hex_')):
                symbols[parts[2]]=int(parts[0],16)
        if any(k not in symbols for k in ('dizi_entry_trampoline','dizi_sctlr_trampoline','entry_resume','sctlr_resume')):
            raise ValueError('Missing essential labels')
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(p/'trace.o'),str(p/'trace.bin')],check=True)
        blob=bytearray((p/'trace.bin').read_bytes())
    if CAVE+len(blob)>=VECTOR_START or len(blob)>LIMIT-CAVE:
        raise ValueError(f'Register viewer overlaps code/vector at {len(blob)} bytes')
    for label,_ in REGS:
        name='hex_'+label.lower().replace(' ','_')
        pos=symbols[name]
        if blob[pos:pos+16]!=b'0'*16:
            raise ValueError('Unexpected missing hex field: '+name)
    for label,target in (('entry_resume',FIRST),('sctlr_resume',SCTLR)):
        at=symbols[label]
        if struct.unpack_from('<I',blob,at)[0]!=0xd503201f:
            raise ValueError('Return trampoline is not a NOP')
        struct.pack_into('<I',blob,at,core.arm_b(CAVE+at,target))
    return bytes(blob),symbols


def build(source:Path,output:Path,report:Path):
    if source.resolve()==output.resolve():raise ValueError('Refusing in-place patch')
    boot=source.read_bytes()
    if len(boot)!=core.BOOT_SIZE or sha(boot)!=BASE_BOOT_SHA or boot[:8]!=b'ANDROID!':
        raise ValueError('Expected exact hardware-proven text-b boot-v4')
    if struct.unpack_from('<I',boot,40)[0]!=4:
        raise ValueError('Wrong Android boot header version')
    old=boot[core.KERNEL_OFFSET:core.KERNEL_OFFSET+core.KERNEL_SIZE]
    if sha(old)!=BASE_MACHO_SHA:raise ValueError('Wrong hardware-proven text-b Mach-O')
    kernel=bytearray(old)
    if struct.unpack_from('<II',kernel,core.offset(kernel,SCTLR))!=(0xd5181000,0xd5033fdf):
        raise ValueError('Native SCTLR and ISB changed')
    if struct.unpack_from('<II',kernel,core.offset(kernel,0xfffffff0073f2368))!=(0xeb01001f,0x54000001):
        raise ValueError('Native compare/guard changed')
    for site,original,_ in textb.RESTORE:
        if struct.unpack_from('<I',kernel,core.offset(kernel,site))[0]!=original:
            raise ValueError(f'Old restored ARM64 instruction changed: {site:#x}')
    old_entry=core.arm_b(ENTRY,CAVE)
    old_pre=core.arm_b(PRE,CAVE+16)
    if struct.unpack_from('<I',kernel,core.offset(kernel,ENTRY))[0]!=old_entry or struct.unpack_from('<I',kernel,core.offset(kernel,PRE))[0]!=old_pre:
        raise ValueError('Old text-b trampoline hooks changed')
    blob,sym=assemble()
    start=core.offset(kernel,CAVE);end=core.offset(kernel,LIMIT)
    # Source Mach-O SHA pins the entire old cave, including old text data.
    kernel[start:end]=bytes(end-start)
    kernel[start:start+len(blob)]=blob
    struct.pack_into('<I',kernel,core.offset(kernel,ENTRY),core.arm_b(ENTRY,CAVE+sym['dizi_entry_trampoline']))
    struct.pack_into('<I',kernel,core.offset(kernel,PRE),core.arm_b(PRE,CAVE+sym['dizi_sctlr_trampoline']))
    allowed=set(range(start,end))|set(range(core.offset(kernel,ENTRY),core.offset(kernel,ENTRY)+4))|set(range(core.offset(kernel,PRE),core.offset(kernel,PRE)+4))
    diffs=[i for i,(a,b) in enumerate(zip(old,kernel)) if a!=b]
    if any(i not in allowed for i in diffs):raise ValueError('Changed bytes outside existing diagnostic cave/hooks')
    out=bytearray(boot)
    for i in diffs:out[core.KERNEL_OFFSET+i]=kernel[i]
    newboot=sha(out);newmacho=sha(kernel)
    if newboot!=OUTPUT_BOOT_SHA or newmacho!=OUTPUT_MACHO_SHA:
        raise ValueError('Binary differs from pinned tested output: '+newboot+' / '+newmacho)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(out)
    meta={'variant':'regs-b','pre_sctlr_registers':[name for name,_ in REGS],
          'input_text_b_boot_sha256':BASE_BOOT_SHA,'input_text_b_macho_sha256':BASE_MACHO_SHA,
          'output_boot_sha256':newboot,'output_macho_sha256':newmacho,
          'tracer_cave_size':len(blob),'max_cave_size':LIMIT-CAVE,
          'modified_macho_bytes':len(diffs),'no_changes_to_native_sctlr_isb_cmp_branch':True,
          'post_mmu_fb_writes':False,'hardware_tested':False,
          'note':'SCTLR OLD is read BEFORE SCTLR_EL1 is written. Register values are actual EL1 reads, but mapped page table descriptors are not independently checked.',
          'warning':'HIGH RISK: fastboot boot only. NEVER fastboot flash.'}
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

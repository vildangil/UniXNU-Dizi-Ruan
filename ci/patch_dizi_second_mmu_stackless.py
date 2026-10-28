#!/usr/bin/env python3
"""Controlled dizi MMU A/B: change only the SECOND Y432 checkpoint to stackless.

Input exact first-NO-SP Mach-O SHA. Existing Y408 marker, four later MMU
markers, TTBR1, SCTLR and ISB remain byte-identical. New stub clobbers
x9-x11 and NZCV, as earlier successful stackless diagnostic stubs did.
Not a production kernel patch and not proof of native MMU initialization.
"""
import argparse,hashlib,json,shutil,struct,subprocess,tempfile
from pathlib import Path

SHA='5d5666cdb13c64665cb393676806d02a38972660e89cb02547059032c6b40fba'
MARK='DIZI_FIRST_TWO_MMU_STAGES_STACKLESS_V1'
ENTRY=0xFFFFFFF0073F0488
PINK_STUB=ENTRY+0x200
SECOND_STUB=ENTRY+0x254
THIRD_STUB=ENTRY+0x2A8
FIRST_HOOK=0xFFFFFFF0073F22B4
TTBR1=0xFFFFFFF0073F22B8
SECOND_HOOK=0xFFFFFFF0073F22BC
SECOND_ORIGINAL=0xAA1F03E0
SCTLR=0xFFFFFFF0073F2350

def arm_branch(src,dst):
    d=dst-src
    if d%4 or not -(1<<27)<=d<(1<<27):
        raise ValueError('ARM64 B target out of range')
    return 0x14000000|((d>>2)&0x3ffffff)

def off(data,va):
    if len(data)<4096 or struct.unpack_from('<I',data)[0]!=0xFEEDFACF:
        raise ValueError('Not Mach-O64')
    n,cmdlen=struct.unpack_from('<II',data,16)
    if not 0<n<256 or cmdlen>len(data)-32:
        raise ValueError('Invalid Mach-O load command table')
    pos=32
    for _ in range(n):
        typ,sz=struct.unpack_from('<II',data,pos)
        if sz<8 or pos+sz>len(data):
            raise ValueError('Corrupt Mach-O load command')
        if typ==0x19:
            name,vm,vm_sz,fo,fs=struct.unpack_from('<16sQQQQ',data,pos+8)
            if name.rstrip(b'\0')==b'__TEXT_EXEC' and vm<=va<vm+min(vm_sz,fs):
                offset=fo+va-vm
                if offset+4>len(data):
                    raise ValueError('Truncated executable Mach-O')
                return offset
        pos+=sz
    raise ValueError('VA not file-backed __TEXT_EXEC: '+hex(va))

def no_sp_code():
    cc=shutil.which('clang-18') or shutil.which('clang')
    obj=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    if not cc or not obj: raise RuntimeError('clang + llvm-objcopy required')
    # Framebuffer PA = B8000000 + 432*6400 = B82A3000
    asm="""
.section .text.nosp,"ax",%progbits
.global dizi_second_mmu_no_sp
dizi_second_mmu_no_sp:
  movz x9, #0x3000
  movk x9, #0xb82a, lsl #16
  movz w10, #0x4500
  movk w10, #0xffff, lsl #16
  movz w11, #7200
1:
  stp w10, w10, [x9], #8
  subs w11, w11, #1
  b.ne 1b
  dsb sy
  .inst 0xaa1f03e0
  nop
"""
    with tempfile.TemporaryDirectory(prefix='dizi-second-nosp-') as tmp:
        p=Path(tmp)
        (p/'probe.S').write_text(asm)
        subprocess.run([cc,'--target=aarch64-none-elf','-c',str(p/'probe.S'),'-o',str(p/'probe.o')],check=True)
        subprocess.run([obj,'-O','binary','-j','.text.nosp',str(p/'probe.o'),str(p/'probe.bin')],check=True)
        b=bytearray((p/'probe.bin').read_bytes())
    if len(b)!=44 or struct.unpack_from('<II',b,36)!=(SECOND_ORIGINAL,0xD503201F):
        raise ValueError('Wrong compiled checkpoint')
    struct.pack_into('<I',b,40,arm_branch(SECOND_STUB+40,SECOND_HOOK+4))
    region=THIRD_STUB-SECOND_STUB
    if region!=84: raise ValueError('Unexpected reservation')
    b+=struct.pack('<I',0xD503201F)*((region-len(b))//4)
    if len(b)!=region:raise ValueError('Wrong padded code size')
    return b

def patch(input_path,output_path,report):
    if input_path.resolve()==output_path.resolve():
        raise ValueError('Refuse source overwrite')
    b=bytearray(input_path.read_bytes())
    h=hashlib.sha256(b).hexdigest()
    if h!=SHA:raise ValueError('Pinned FIRST-NOSP input hash mismatch: '+h)
    first,second,third=(off(b,va) for va in (PINK_STUB,SECOND_STUB,THIRD_STUB))
    hook=off(b,SECOND_HOOK)
    if third-second!=84 or second-first!=84:raise ValueError('Cave layout changed')
    if struct.unpack_from('<I',b,first)[0]!=0xD29B0009:raise ValueError('First pink no-SP marker absent')
    if struct.unpack_from('<I',b,second)[0]!=0xD100C3FF:raise ValueError('Second marker is not original SP probe')
    if struct.unpack_from('<I',b,third)[0]!=0xD100C3FF:raise ValueError('Third marker changed')
    if struct.unpack_from('<I',b,hook)[0]!=arm_branch(SECOND_HOOK,SECOND_STUB):
        raise ValueError('Second hook does not branch to stub')
    if struct.unpack_from('<I',b,off(b,FIRST_HOOK))[0]!=arm_branch(FIRST_HOOK,PINK_STUB):
        raise ValueError('First pink hook missing')
    if struct.unpack_from('<I',b,off(b,TTBR1))[0]!=0xD5182020:
        raise ValueError('TTBR1 original MSR changed')
    if struct.unpack_from('<II',b,off(b,SCTLR))!=(0xD5181000,0xD5033FDF):
        raise ValueError('SCTLR original MSR and ISB changed')
    old=bytes(b)
    b[second:third]=no_sp_code()
    diffs=[i for i,(a,c) in enumerate(zip(old,b)) if a!=c]
    if not diffs or min(diffs)<second or max(diffs)>=third:
        raise AssertionError('Unexpected modification outside second marker')
    if b[first:second]!=old[first:second] or b[third:]!=old[third:] or len(b)!=len(old):
        raise AssertionError('First or other MMU checkpoints changed')
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_bytes(b)
    meta={'marker':MARK,'input_sha256':h,
          'patched_sha256':hashlib.sha256(b).hexdigest(),'size':len(b),
          'second_stub_va':hex(SECOND_STUB),'second_hook_va':hex(SECOND_HOOK),
          'return_va':hex(SECOND_HOOK+4),'changed_byte_count':len(diffs),
          'modified_region_bytes':84,'only_second_checkpoint_modified':True,
          'first_pink_checkpoint_preserved':True,
          'remaining_four_checkpoints_preserved':True,
          'ttbr1_sctlr_isb_original':True,'second_checkpoint_stackless':True,
          'first_pink_y':[408,416],'second_orange_red_y':[432,440],
          'native_mmu_enabled_confirmed':False,
          'interpretation':'Y432 confirms reaching second probe after TTBR1 but does not prove stack or MMU-on.'}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args()
    patch(a.input,a.output,a.report)

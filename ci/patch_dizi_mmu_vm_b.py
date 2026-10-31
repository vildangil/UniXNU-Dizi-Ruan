#!/usr/bin/env python3
"""Build VM-B only from the SHA-locked, photographed FLOW-B image.

Relocate BL/ADRP explicitly; never execute their original encodings in a cave.
No vector, MMIO, PSCI or additional page-table writes. cpus=1 unchanged.
"""
from __future__ import annotations
import argparse, json, struct, subprocess, tempfile, shutil
from pathlib import Path
import patch_dizi_mmu_flow_b as flow
from check_dizi_flow_b_source import FONT_SHA

EXTRA=(
 ('9 VM ENTRY',0xfffffff0073e95dc,0xaa0103fa),
 ('A VM RAM',0xfffffff0073e9644,0xf0ffec09),
 ('B VM PHYSMAP',0xfffffff0073e9698,0xf0ffec13),
 ('C VM ENTROPY',0xfffffff0073e96a4,0x92407415),
 ('D VM TABLES',0xfffffff0073e97f8,0xf0ffec08),
 ('E VM SEGMENTS',0xfffffff0073e9cd4,0xf0ffec13),
 ('F VM MAP READY',0xfffffff0073ea104,0xf9400108),
 ('G VM SWITCH',0xfffffff0073ea108,0x9240bd00),
)
SITES=flow.SITES+EXTRA
# Filled after independent local reproduction; output changes require review.
OUTPUT_BOOT='7947442d0f41c55ba60104cf9d91a1ed5eb932c766dd5c228323845500850ed2'
OUTPUT_MACHO='dd69bc6d1a34e99a25a9e4792d36fe08b43796e3f7220b5be063cc40a78ab929'

def signed(v,bits):
    return v-(1<<bits) if v&(1<<(bits-1)) else v

def adrp(pc,target,rd):
    delta=(target>>12)-(pc>>12)
    if not -(1<<20)<=delta<(1<<20): raise ValueError('ADRP range')
    imm=delta&0x1fffff
    return 0x90000000|((imm&3)<<29)|((imm>>2)<<5)|rd

def displaced(site,op,pc):
    if op>>26==0x25: # BL: restore its native link address then tail-branch.
        target=site+signed(op&0x3ffffff,26)*4
        link=site+4
        return [adrp(pc,link,30),0x910003de|((link&0xfff)<<10),flow.branch(pc+8,target)]
    if op&0x9f000000==0x90000000:
        imm=((op>>29)&3)|(((op>>5)&0x7ffff)<<2)
        target=(site&~0xfff)+(signed(imm,21)<<12)
        return [adrp(pc,target,op&31),flow.branch(pc+4,site+4)]
    return [op,flow.branch(pc+4,site+4)]

def assemble(kernel):
    template=Path(__file__).with_name('dizi_mmu_flow_b.S.in').read_text()
    # Reuse the audited register/flags-preserving common body and renderer.
    common=template[template.index('trace_common:'):template.index('.p2align 2\nfont5_table:')]
    # Two columns of eight persistent rows; no pixel exceeds first 2MiB.
    common=common.replace('movz x10,#2600','movz x10,#80\n    cmp w0,#8\n    b.hi trace_left\n    movz x10,#2600\ntrace_left:')
    common=common.replace('movz x1,#34','mov x2,x0\n    cmp w2,#8\n    b.ls trace_row\n    sub w2,w2,#8\ntrace_row:\n    movz x1,#34').replace('mul x1,x0,x1','mul x1,x2,x1')
    # Clear the already-mapped 2MiB once, before first flow marker. The
    # retained legacy diagnostics have all run by this point. No new mapping.
    clear='''    cmp w0,#1
    b.ne trace_no_clear
    movz x10,#2,lsl#16
    mov x11,x9
trace_clear:
    stp xzr,xzr,[x11],#16
    subs x10,x10,#1
    b.ne trace_clear
    dsb sy
trace_no_clear:
'''
    common=common.replace('    movz x10,#80',clear+'    movz x10,#80')
    a=common.index('    cmp w0,#1',common.index('madd x7')); b=common.index('trace_draw:')
    dispatch=''.join(f'    cmp w0,#{i}\n    b.eq trace_msg_{i}\n' for i in range(1,17))+'    ret\n'
    dispatch+=''.join(f'trace_msg_{i}:\n    adr x15,msg_{i}\n    b trace_draw\n' for i in range(1,17))
    common=common[:a]+dispatch+common[b:]
    src='.section .text.trace,"ax",%progbits\n.p2align 2\n'
    entries=[]; offset=0
    for i,(_,site,op) in enumerate(SITES,1):
        entries.append(offset)
        # Entry: save scratch pair before ADR/MOV; shared body saves NZCV.
        src+=f'trace_hit_{i}:\n stp x12,x13,[sp,#-16]!\n adr x12,trace_resume_{i}\n movz w13,#{i}\n b trace_common\ntrace_resume_{i}:\n ldp x12,x13,[sp],#16\n'
        words=displaced(site,op,flow.CAVE+offset+20)
        src+=''.join(f' .inst {w:#x}\n' for w in words)
        offset+=20+4*len(words)
    font=kernel[flow.off(kernel,0xfffffff0073f0d90):flow.off(kernel,0xfffffff0073f0d90)+413]
    if flow.sha(font)!=FONT_SHA: raise ValueError('Font SHA mismatch')
    src+=common+'\n.p2align 2\nfont5_table:\n.byte '+','.join(map(str,font))+'\n'
    src+=''.join(f'msg_{i}: .asciz "{name if i>8 else str(i)+" "+name}"\n' for i,(name,_,_) in enumerate(SITES,1))
    if src != Path(__file__).with_name('dizi_mmu_vm_b.generated.S').read_text():
        raise ValueError('Generated assembly differs from reviewed source')
    clang=shutil.which('clang-19') or shutil.which('clang-18') or shutil.which('clang')
    copy=shutil.which('llvm-objcopy-19') or shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    if not clang or not copy: raise RuntimeError('Need clang and llvm-objcopy')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp); (p/'init.S').write_text(src)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(p/'init.S'),'-o',str(p/'init.o')],check=True)
        reloc=subprocess.check_output(['readelf','-r',str(p/'init.o')],text=True)
        if 'There are no relocations in this file' not in reloc: raise ValueError('Unresolved relocations')
        subprocess.run([copy,'-O','binary','-j','.text.trace',str(p/'init.o'),str(p/'init.bin')],check=True)
        code=(p/'init.bin').read_bytes()
    if len(code)>flow.CAVE_END-flow.CAVE: raise ValueError('Cave overflow')
    return code,entries,src

def build(inp,dst,report):
    if inp.resolve()==dst.resolve(): raise ValueError('Refusing input overwrite')
    boot=inp.read_bytes()
    if len(boot)!=flow.BOOT_BYTES or flow.sha(boot)!=flow.OUTPUT_BOOT: raise ValueError('Expected exact FLOW-B')
    orig=boot[flow.MACHO_OFF:flow.MACHO_OFF+flow.MACHO_BYTES]
    if flow.sha(orig)!=flow.OUTPUT_MACHO: raise ValueError('Mach-O SHA mismatch')
    # Undo only the pinned FLOW-B tracer, verifying underlying ARCH-B SHA.
    kernel=bytearray(orig); start=flow.off(orig,flow.CAVE); end=flow.off(orig,flow.CAVE_END)
    kernel[start:end]=bytes(end-start)
    for _,site,op in flow.SITES: struct.pack_into('<I',kernel,flow.off(kernel,site),op)
    if flow.sha(kernel)!=flow.SOURCE_MACHO: raise ValueError('Cannot recover pinned ARCH-B')
    for name,site,op in SITES:
        if struct.unpack_from('<I',kernel,flow.off(kernel,site))[0]!=op: raise ValueError('Opcode mismatch '+name)
    code,entries,src=assemble(kernel)
    kernel[start:start+len(code)]=code
    for (_,site,_),entry in zip(SITES,entries):
        struct.pack_into('<I',kernel,flow.off(kernel,site),flow.branch(site,flow.CAVE+entry))
    allowed=set(range(start,end))
    for _,site,_ in SITES: allowed.update(range(flow.off(orig,site),flow.off(orig,site)+4))
    diffs=[i for i,(a,b) in enumerate(zip(orig,kernel)) if a!=b]
    if any(i not in allowed for i in diffs): raise ValueError('Change outside approved locations')
    result=bytearray(boot); result[flow.MACHO_OFF:flow.MACHO_OFF+flow.MACHO_BYTES]=kernel
    if flow.sha(result)!=OUTPUT_BOOT or flow.sha(kernel)!=OUTPUT_MACHO: raise ValueError('Output SHA mismatch: '+flow.sha(result)+' '+flow.sha(kernel))
    dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(result)
    audit={'variant':'vm-b','hardware_tested':False,'input_boot_sha256':flow.OUTPUT_BOOT,'output_boot_sha256':flow.sha(result),'output_macho_sha256':flow.sha(kernel),'payload_sha256':flow.sha(code),'payload_bytes':len(code),'changed_kernel_bytes':len(diffs),'hook_sites':[{'stage':n,'va':hex(s),'original_opcode':hex(o)} for n,s,o in SITES],'new_vector_handler':False,'extra_page_table_writes':False,'extra_psci_calls':False,'cave_bytes':end-start,'stack_bytes':192,'limitation':'G precedes native TTBR0/TTBR1 replacement; no post-switch framebuffer writes added; native VM can continue without further output','safety':'Temporary fastboot boot only; cpus=1'}
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(audit,indent=2)+'\n')
    dst.with_suffix('.S').write_text(src)
    print(json.dumps(audit,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('input','output','report'): p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

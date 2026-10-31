#!/usr/bin/env python3
"""Bounded read-only pre-switch L1/L2 audit; never install mappings."""
import argparse,json
from pathlib import Path
import patch_dizi_mmu_vm_b as vm
flow=vm.flow
SITES=tuple(vm.EXTRA[i] for i in (0,4,6))+(('G MAP AUDIT',0xfffffff0073ea0b0,0xd0ffec08),)
signed=vm.signed
OUTPUT_BOOT='5479a94e36a2e3527131c9401ff98e1024bf3fc6f4356952a5e901cf720eb4e3'
OUTPUT_MACHO='0e501f962531c0143fb84727ec8c6370dc2cb61c30ec1ef0bdab927d1a63d1e5'

def transform(src):
    # Four VM markers at left; eight numeric rows at right. No early flow hooks.
    src=src.replace('movz x10,#2600','movz x10,#80')
    for i,(name,_,_) in enumerate(SITES,1):src=src.replace(f'"{i} {name}"',f'"{name}"')
    src=src.replace('    bl trace_render\n','    bl trace_render\n    ldr x9,[sp,#104]\n    cmp w9,#4\n    b.ne table_skip\n    bl table_snapshot\ntable_skip:\n')
    routine='''
table_snapshot:
    sub sp,sp,#128
    stp x19,x20,[sp,#96]
    stp x21,x30,[sp,#112]
    stp xzr,xzr,[sp,#32]
    stp xzr,xzr,[sp,#48]
    stp xzr,xzr,[sp,#64]
    stp xzr,xzr,[sp,#80]
    movz x19,#0xabb0
    movk x19,#0x0716,lsl#16
    movk x19,#0xfff0,lsl#32
    movk x19,#0xffff,lsl#48
    ldr x20,[x19,#8]
    str x20,[sp,#32]
    mrs x4,TCR_EL1
    str x4,[sp,#88]
    movz x5,#0x251a
    movk x5,#0xa51a,lsl#16
    movk x5,#0x22,lsl#32
    mov x21,#1
    cmp x4,x5
    b.ne table_result
    ldr x19,[x19]
    str x19,[sp,#40]
    mov x21,#2
    tst x19,#0xfff
    b.ne table_result
    asr x5,x19,#38
    cmn x5,#1
    b.ne table_result
    ldr x4,[x19,#0x600]
    str x4,[sp,#48]
    mov x21,#3
    and x5,x4,#3
    cmp x5,#3
    b.ne table_result
    and x19,x4,#0xfffffffff000
    str x19,[sp,#56]
    mov x21,#4
    cmp x19,x20
    b.lo table_result
    movz x5,#0xc000
    movk x5,#0x0716,lsl#16
    movk x5,#0xfff0,lsl#32
    movk x5,#0xffff,lsl#48
    ldr x6,[x5,#0x138]
    add x7,x19,#0x1000
    cmp x7,x6
    b.hi table_result
    // Also bound the child to native gPhysBase / mem_size before phystokv.
    ldr x6,[x5,#0x108]
    cmp x19,x6
    b.lo table_result
    sub x7,x7,x6
    ldr x6,[x5,#0x110]
    cmp x7,x6
    b.hi table_result
    mov x0,x19
    movz x16,#0x8784
    movk x16,#0x073e,lsl#16
    movk x16,#0xfff0,lsl#32
    movk x16,#0xffff,lsl#48
    blr x16
    mov x21,#5
    tst x0,#0xfff
    b.ne table_result
    asr x5,x0,#38
    cmn x5,#1
    b.ne table_result
    ldr x4,[x0,#0x100]
    ldr x5,[x0,#0x1c8]
    stp x4,x5,[sp,#64]
    mov x21,#0
table_result:
    str x21,[sp,#80]
    mov x19,#1
table_row:
    add x6,sp,#24
    ldr x4,[x6,x19,lsl#3]
    adr x5,table_labels
    sub x6,x19,#1
    ldrb w5,[x5,x6]
    strb w5,[sp]
    mov w5,#32
    strb w5,[sp,#1]
    add x6,sp,#2
    mov x5,#16
    adr x14,table_digits
table_hex:
    lsr x8,x4,#60
    ldrb w8,[x14,x8]
    strb w8,[x6],#1
    lsl x4,x4,#4
    subs x5,x5,#1
    b.ne table_hex
    strb wzr,[x6]
    movz x7,#0x0400,lsl#16
    movk x7,#0xfff0,lsl#32
    movk x7,#0xffff,lsl#48
    mov x3,#6400
    mov x9,#34
    mul x9,x19,x9
    add x9,x9,#10
    madd x7,x9,x3,x7
    add x7,x7,#2600
    mov x15,sp
    bl trace_draw
    add x19,x19,#1
    cmp x19,#9
    b.ne table_row
    ldp x19,x20,[sp,#96]
    ldp x21,x30,[sp,#112]
    add sp,sp,#128
    ret
table_digits: .ascii "0123456789ABCDEF"
table_labels: .ascii "NVLPFKST"
.p2align 2
'''
    return src.replace('.p2align 2\nfont5_table:',routine+'.p2align 2\nfont5_table:')

def assemble(kernel):return vm.assemble(kernel,source_transform=transform,review_source='dizi_mmu_table_b.generated.S',sites=SITES)

def build(inp,dst,report):
    vm.build(inp,dst,report,variant='table-b',assembler=assemble,expected_boot=OUTPUT_BOOT,expected_macho=OUTPUT_MACHO,sites=SITES)
    r=json.loads(report.read_text());r.update({'stack_bytes':320,'numeric_fields':{'N':'prospective root PA from native global 0xFFFFFFF00716ABB8','V':'native virtual root pointer','L':'new L1[C0] descriptor','P':'child table PA','F':'new L2[20] framebuffer descriptor','K':'new L2[39] kernel descriptor','S':'status 0=read complete, 1=TCR mismatch, 2=root pointer rejected, 3=L1 not table, 4=child outside native allocation/RAM bounds, 5=converted pointer rejected','T':'TCR_EL1'},'native_helper_called':'phystokv, only for bounded native-allocated child page','limitation':'Reads before physmap metadata replacement at 0xFFFFFFF0073EA0B0, before TTBR switch; F/K can be L3 table descriptors, so their validity alone does not prove final leaf translation. S=0 means reads completed, not a healthy mapping.'});report.write_text(json.dumps(r,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('input','output','report'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

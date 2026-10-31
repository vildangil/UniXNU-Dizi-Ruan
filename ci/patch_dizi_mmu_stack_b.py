#!/usr/bin/env python3
"""Read-only active-stack/data translation walk in prospective TTBR0/TTBR1."""
import argparse,json
from pathlib import Path
import patch_dizi_mmu_table_b as table
vm=table.vm
flow=table.flow
SITES=table.SITES
signed=table.signed
OUTPUT_BOOT='0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed'
OUTPUT_MACHO='396b1c94f6024efbd534957ea9fc6708ab1178997d2ae7fcf6ba61d3afc59f3d'

def transform(src):
    src=src.replace('movz x10,#2600','movz x10,#80')
    for i,(name,_,_) in enumerate(SITES,1):src=src.replace(f'"{i} {name}"',f'"{name}"')
    src=src.replace('    bl trace_render\n','    bl trace_render\n    ldr x9,[sp,#104]\n    cmp w9,#4\n    b.ne stack_skip\n    bl stack_snapshot\nstack_skip:\n')
    routine='''
stack_snapshot:
    sub sp,sp,#192
    stp x19,x20,[sp,#96]
    stp x21,x22,[sp,#112]
    stp x23,x24,[sp,#128]
    stp x25,x26,[sp,#144]
    stp x27,x28,[sp,#160]
    stp x29,x30,[sp,#176]
    stp xzr,xzr,[sp,#32]
    stp xzr,xzr,[sp,#48]
    stp xzr,xzr,[sp,#64]
    stp xzr,xzr,[sp,#80]
    add x4,sp,#384
    str x4,[sp,#32]
    mrs x4,TCR_EL1
    movz x5,#0x251a
    movk x5,#0xa51a,lsl#16
    movk x5,#0x22,lsl#32
    cmp x4,x5
    b.eq stack_begin
    movz x4,#0x0101
    movk x4,#0x0101,lsl#16
    str x4,[sp,#88]
    b stack_print
stack_begin:
    mov x19,#1
stack_target:
    add x0,sp,#384
    cmp x19,#1
    b.ne stack_bottom
    sub x0,x0,#8
    b stack_capture
stack_bottom:
    cmp x19,#2
    b.ne stack_global
    sub x0,x0,#384
    b stack_capture
stack_global:
    movz x0,#0xabb8
    cmp x19,#3
    b.eq stack_global_high
    movz x0,#0xc048
stack_global_high:
    movk x0,#0x0716,lsl#16
    movk x0,#0xfff0,lsl#32
    movk x0,#0xffff,lsl#48
stack_capture:
    bl future_walk
    cmp x19,#1
    b.ne stack_store
    str x3,[sp,#80]
stack_store:
    mov x5,x4
    add x4,sp,#32
    str x0,[x4,x19,lsl#3]
    sub x6,x19,#1
    lsl x7,x6,#2
    lsl x2,x2,x7
    ldr x4,[sp,#72]
    orr x4,x4,x2
    add x7,x6,#16
    lsl x5,x5,x7
    orr x4,x4,x5
    str x4,[sp,#72]
    lsl x7,x6,#3
    lsl x1,x1,x7
    ldr x4,[sp,#88]
    orr x4,x4,x1
    str x4,[sp,#88]
    add x19,x19,#1
    cmp x19,#5
    b.ne stack_target
stack_print:
    mov x19,#1
stack_row:
    add x6,sp,#24
    ldr x4,[x6,x19,lsl#3]
    adr x5,stack_labels
    sub x6,x19,#1
    ldrb w5,[x5,x6]
    strb w5,[sp]
    mov w5,#32
    strb w5,[sp,#1]
    add x6,sp,#2
    mov x5,#16
    adr x14,stack_digits
stack_hex:
    lsr x8,x4,#60
    ldrb w8,[x14,x8]
    strb w8,[x6],#1
    lsl x4,x4,#4
    subs x5,x5,#1
    b.ne stack_hex
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
    b.ne stack_row
    ldp x19,x20,[sp,#96]
    ldp x21,x22,[sp,#112]
    ldp x23,x24,[sp,#128]
    ldp x25,x26,[sp,#144]
    ldp x27,x28,[sp,#160]
    ldp x29,x30,[sp,#176]
    add sp,sp,#192
    ret
// x0=VA -> raw terminal descriptor, status, level, root PA, ancestor RO.
// x19 is the caller's loop counter; x20..x28 are saved by snapshot.
future_walk:
    mov x28,x30
    mov x21,x0
    mov x22,#1
    mov x27,#0
    mov x23,#0
    lsr x4,x0,#38
    cbz x4,walk_lower
    asr x4,x0,#38
    cmn x4,#1
    b.ne walk_bad_va
    mov x6,#16
    b walk_roots
walk_lower:
    mov x6,#0
walk_roots:
    movz x23,#0xaba0
    movk x23,#0x0716,lsl#16
    movk x23,#0xfff0,lsl#32
    movk x23,#0xffff,lsl#48
    ldr x20,[x23,#8]
    ldr x5,[x23,#24]
    cbz x20,walk_bad_root
    cbz x5,walk_bad_root
    orr x4,x20,x5
    tst x4,#0xfff
    b.ne walk_bad_root
    lsr x4,x4,#40
    cbnz x4,walk_bad_root
    cmp x20,x5
    csel x20,x20,x5,lo
    add x23,x23,x6
    ldp x24,x27,[x23]
    mov x23,#0
    tst x24,#0xfff
    b.ne walk_bad_root
    asr x4,x24,#38
    cmn x4,#1
    b.ne walk_bad_root
walk_level:
    mov x4,#3
    sub x4,x4,x22
    mov x5,#9
    mul x4,x4,x5
    add x4,x4,#12
    lsrv x5,x21,x4
    cmp x22,#1
    mov x6,#0xff
    mov x7,#0x1ff
    csel x6,x6,x7,eq
    and x5,x5,x6
    ldr x25,[x24,x5,lsl#3]
    cmp x22,#3
    b.eq walk_done
    tbz x25,#0,walk_done
    tbz x25,#1,walk_done
    tbz x25,#62,walk_child
    orr x23,x23,#1
walk_child:
    and x0,x25,#0xfffffffff000
    cmp x0,x20
    b.lo walk_bad_bounds
    movz x26,#0xc000
    movk x26,#0x0716,lsl#16
    movk x26,#0xfff0,lsl#32
    movk x26,#0xffff,lsl#48
    ldr x4,[x26,#0x138]
    add x5,x0,#0x1000
    cmp x5,x4
    b.hi walk_bad_bounds
    ldr x4,[x26,#0x108]
    cmp x0,x4
    b.lo walk_bad_bounds
    sub x5,x5,x4
    ldr x4,[x26,#0x110]
    cmp x5,x4
    b.hi walk_bad_bounds
    movz x16,#0x8784
    movk x16,#0x073e,lsl#16
    movk x16,#0xfff0,lsl#32
    movk x16,#0xffff,lsl#48
    blr x16
    tst x0,#0xfff
    b.ne walk_bad_pointer
    asr x4,x0,#38
    cmn x4,#1
    b.ne walk_bad_pointer
    mov x24,x0
    add x22,x22,#1
    b walk_level
walk_done:
    mov x0,x25
    mov x1,#0
    b walk_return
walk_bad_va:
    mov x23,#0
    mov x1,#2
    b walk_failed
walk_bad_root:
    mov x23,#0
    mov x1,#3
    b walk_failed
walk_bad_bounds:
    mov x1,#4
    b walk_failed
walk_bad_pointer:
    mov x1,#5
walk_failed:
    mov x0,#0
walk_return:
    mov x2,x22
    mov x3,x27
    mov x4,x23
    br x28
stack_digits: .ascii "0123456789ABCDEF"
stack_labels: .ascii "BPQDMLRS"
.p2align 2
'''
    return src.replace('.p2align 2\nfont5_table:',routine+'.p2align 2\nfont5_table:')

def assemble(kernel):return vm.assemble(kernel,source_transform=transform,review_source='dizi_mmu_stack_b.generated.S',sites=SITES)

def build(inp,dst,report):
    vm.build(inp,dst,report,variant='stack-b',assembler=assemble,expected_boot=OUTPUT_BOOT,expected_macho=OUTPUT_MACHO,sites=SITES)
    r=json.loads(report.read_text());r.update({'stack_bytes':384,'numeric_fields':{'B':'active native SP at probe','P':'terminal descriptor for SP-8','Q':'terminal descriptor for SP-384','D':'terminal descriptor for root-global page 0xFFFFFFF00716ABB8','M':'terminal descriptor for physmap metadata page 0xFFFFFFF00716C048','L':'P/Q/D/M terminal-level nibbles bits0..15, ancestor EL1-readonly bits16..19','R':'prospective root PA selected for SP-8 (TTBR0 or TTBR1)','S':'P/Q/D/M status bytes low to high: 0=terminal read, 1=TCR mismatch, 2=noncanonical target, 3=root rejected, 4=child bounds rejected, 5=converted VA rejected'},'walk_roots':'native prospective TTBR0 pair at ...716ABA0 and TTBR1 pair at ...716ABB0','extra_page_table_writes':False,'limitation':'Invalid terminal descriptors are real readbacks when status=0; nonzero status values denote skipped terminal reads. No effective post-switch access or alias fix.'});report.write_text(json.dumps(r,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('input','output','report'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

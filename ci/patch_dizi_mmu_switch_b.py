#!/usr/bin/env python3
"""Read-only pre-switch roots, no post-switch framebuffer access or table edits."""
import argparse,json
from pathlib import Path
import patch_dizi_mmu_vm_b as vm
flow=vm.flow
SITES=vm.SITES
OUTPUT_BOOT='b4e33fd8fc6064546e31083f589a691184c0e5fc52766ba32c05723597b31bc4'
OUTPUT_MACHO='5ada52955c15d1a68a2828e21b91312c6cb27a0ec6af8682c03189c2b6e25fbd'
signed=vm.signed

def transform(src):
    # Reserve the right column for numeric evidence; keep all native hooks.
    src=src.replace('trace_no_clear:\n','trace_no_clear:\n    cmp w0,#8\n    b.ls trace_done\n')
    src=src.replace('    bl trace_render\n','    bl trace_render\n    ldr x9,[sp,#104]\n    cmp w9,#16\n    b.ne snapshot_skip\n    bl root_snapshot\nsnapshot_skip:\n')
    # saved x13 at common frame offset 104 is the stage number.
    routine='''
root_snapshot:
    sub sp,sp,#64
    stp x19,x30,[sp,#48]
    mov x19,#1
root_row:
    cmp x19,#1
    b.ne root_old
    ldr x4,[sp,#128]
    mov w5,#78
    b root_value
root_old:
    cmp x19,#2
    b.ne root_tcr
    mrs x4,TTBR1_EL1
    mov w5,#79
    b root_value
root_tcr:
    mrs x4,TCR_EL1
    mov w5,#84
root_value:
    strb w5,[sp]
    mov w5,#32
    strb w5,[sp,#1]
    add x6,sp,#2
    mov x5,#16
    adr x14,root_digits
root_hex:
    lsr x8,x4,#60
    ldrb w8,[x14,x8]
    strb w8,[x6],#1
    lsl x4,x4,#4
    subs x5,x5,#1
    b.ne root_hex
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
    cmp x19,#4
    b.ne root_row
    ldp x19,x30,[sp,#48]
    add sp,sp,#64
    ret
root_digits: .ascii "0123456789ABCDEF"
.p2align 2
'''
    return src.replace('.p2align 2\nfont5_table:',routine+'.p2align 2\nfont5_table:')

def assemble(kernel):
    return vm.assemble(kernel,source_transform=transform,review_source='dizi_mmu_switch_b.generated.S')

def build(inp,dst,report):
    vm.build(inp,dst,report,variant='switch-b',assembler=assemble,expected_boot=OUTPUT_BOOT,expected_macho=OUTPUT_MACHO)
    r=json.loads(report.read_text());r.update({'stack_bytes':256,'snapshot_fields':{'N':'x8 before native AND: prospective TTBR1 root; high bits are printed unmasked','O':'current TTBR1_EL1','T':'TCR_EL1'},'limitation':'No observation after native TTBR1 replacement. N is not evidence that its tables map the alias.'});report.write_text(json.dumps(r,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('input','output','report'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

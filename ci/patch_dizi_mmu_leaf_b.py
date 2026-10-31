#!/usr/bin/env python3
"""Read-only code/helper/tracer/vector L3 evidence before physmap replacement."""
import argparse,json
from pathlib import Path
import patch_dizi_mmu_table_b as table
vm=table.vm
flow=table.flow
SITES=table.SITES
signed=table.signed
OUTPUT_BOOT='0b5e0f0cebfc10d5e39b8a8f4db316740ad455efd2e154604ff3a2e4ee2e932f'
OUTPUT_MACHO='46cf768c38147b32cfda45c4fc65c9dd014d3ce5832961aa1edf7d4ce3bae50c'

def transform(src):
    src=table.transform(src)
    # Eight fields: N/F/K/C/H/X/V/S. Never print skipped fields as readbacks.
    src=src.replace('    str x4,[sp,#88]\n','')
    src=src.replace('    str x19,[sp,#40]\n','').replace('    str x4,[sp,#48]\n','').replace('    str x19,[sp,#56]\n','')
    needle='    stp x4,x5,[sp,#64]\n    mov x21,#0\ntable_result:\n    str x21,[sp,#80]'
    assert src.count(needle)==1
    extra='''    stp x4,x5,[sp,#40]
    mov x21,#6
    and x6,x5,#3
    cmp x6,#3
    b.ne table_result
    and x19,x5,#0xfffffffff000
    mov x21,#7
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
    mov x21,#8
    tst x0,#0xfff
    b.ne table_result
    asr x5,x0,#38
    cmn x5,#1
    b.ne table_result
    ldr x4,[x0,#0xf50]
    ldr x5,[x0,#0xfb0]
    stp x4,x5,[sp,#56]
    ldr x4,[x0,#0xf88]
    ldr x5,[x0,#0xf68]
    stp x4,x5,[sp,#72]
    mov x21,#0
table_result:
    str x21,[sp,#88]'''
    return src.replace(needle,extra).replace('NVLPFKST','NFKCHXVS')

def assemble(kernel):return vm.assemble(kernel,source_transform=transform,review_source='dizi_mmu_leaf_b.generated.S',sites=SITES)

def build(inp,dst,report):
    vm.build(inp,dst,report,variant='leaf-b',assembler=assemble,expected_boot=OUTPUT_BOOT,expected_macho=OUTPUT_MACHO,sites=SITES)
    r=json.loads(report.read_text());r.update({'stack_bytes':320,'numeric_fields':{'N':'new root PA','F':'framebuffer L2 descriptor','K':'kernel L2 descriptor','C':'L3[1EA], native VM probe/return page','H':'L3[1F6], TTBR helper page','X':'L3[1F1], tracer page','V':'L3[1ED], vector page','S':'0=all leaf reads complete; 1..5=TABLE-B refusals; 6=K not L3 table; 7=L3 child outside bounds; 8=converted L3 VA rejected'},'native_helper':'exact native phystokv twice, only after bounds checks and before gptov replacement','extra_page_table_writes':False,'limitation':'No alias fix or post-switch logger. S=0 is successful capture, not proof of executable valid leaves or kernel progress after switching.'});report.write_text(json.dumps(r,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('input','output','report'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

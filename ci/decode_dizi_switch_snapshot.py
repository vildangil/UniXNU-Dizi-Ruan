#!/usr/bin/env python3
"""Decode captured N/O/T only; never read device memory or infer table contents."""
import argparse,json
from pathlib import Path

def decode(new,old,tcr):
    if (tcr>>30)&3!=2:raise ValueError('Only TTBR1 4KiB granule supported')
    bits=64-((tcr>>16)&63)
    if not 25<=bits<=48:raise ValueError('Unsupported TTBR1 VA width')
    ips=(tcr>>32)&7
    if ips>5:raise ValueError('Unsupported physical-address geometry')
    pa_bits=(32,36,40,42,44,48)[ips]
    levels=(bits-12+8)//9;start=4-levels;topbits=bits-12-9*(levels-1)
    mask=(1<<pa_bits)-1
    roots={}
    for label,value in [('new',new),('old',old)]:
        # Native caller masks x0 to 48 bits. Retain the unmasked snapshot too.
        raw=value&((1<<48)-1)
        if raw&~mask:raise ValueError('Root exceeds configured PA width')
        if raw&((1<<(topbits+3))-1):raise ValueError('Root misaligned for initial table')
        roots[label]={'snapshot':hex(value),'base_pa':hex(raw)}
    targets={}
    for name,va in [('framebuffer',0xfffffff004000000),('tracer',0xfffffff0073f1800),('native_switch',0xfffffff0073ea10c),('vectors',0xfffffff0073ed000)]:
        if va>>(bits)!=(1<<(64-bits))-1:raise ValueError('Target outside TTBR1 canonical region')
        indices={}
        for level in range(start,4):
            width=topbits if level==start else 9
            indices['L'+str(level)]=(va>>(12+9*(3-level)))&((1<<width)-1)
        first=indices['L'+str(start)]
        targets[name]={'va':hex(va),'indices':indices,'new_initial_entry_pa':hex(int(roots['new']['base_pa'],16)+first*8),'old_initial_entry_pa':hex(int(roots['old']['base_pa'],16)+first*8)}
    return {'tcr_el1':hex(tcr),'ttbr1_va_bits':bits,'ttbr1_granule_bytes':4096,'physical_address_bits':pa_bits,'start_level':start,'initial_table_index_bits':topbits,'roots':roots,'roots_differ':new!=old,'targets':targets,'table_descriptors_captured':False,'alias_in_new_tables_verified':False,'ttbr_switch_completed_verified':False,'note':'Initial index is truncated to the configured top-level width, not unconditionally masked to 9 bits; entry addresses are calculations, not memory readbacks.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['new','old','tcr']:p.add_argument('--'+name,type=lambda x:int(x,0),required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=decode(a.new,a.old,a.tcr);a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))

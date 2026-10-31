#!/usr/bin/env python3
"""Decode captured TABLE-B fields; no device memory access or inferred leaf data."""
import argparse,json
from pathlib import Path
from decode_dizi_switch_snapshot import decode

def analyze(fields):
    r={'snapshot':{k:hex(v) for k,v in fields.items()},'probe_status':fields['S'],'framebuffer_absent_at_captured_l2':None,'kernel_leaf_mapping_verified':False,'ttbr_switch_completed_verified':False}
    if fields['S']!=0:
        r['interpretation']='Probe did not complete both L2 reads; zero placeholders must not be treated as descriptor readbacks.'
        return r
    geometry=decode(fields['N'],fields['N'],fields['T'])
    if geometry['targets']['framebuffer']['indices']['L1']!=0xc0:raise ValueError('Unexpected geometry')
    parent=fields['L']
    if parent&3!=3 or (parent&0xfffffffff000)!=fields['P']:raise ValueError('Inconsistent L1/child capture')
    r['l1']={'type':'table','child_pa':hex(fields['P']),'ap_table':(parent>>61)&3,'pxn_table':bool(parent&(1<<59)),'uxn_table':bool(parent&(1<<60))}
    def desc(d):
        if not d&1:return {'type':'invalid','raw':hex(d)}
        if d&3==3:return {'type':'L3_table','raw':hex(d),'child_pa':hex(d&0xfffffffff000)}
        return {'type':'L2_block','raw':hex(d),'physical_base':hex(d&0xffffffe00000),'attr_index':(d>>2)&7,'access_flag':bool(d&(1<<10)),'pxn':bool(d&(1<<53)),'uxn':bool(d&(1<<54))}
    r['framebuffer_l2']=desc(fields['F']);r['kernel_l2']=desc(fields['K'])
    r['framebuffer_absent_at_captured_l2']=not bool(fields['F']&1)
    if fields['K']&3==3:
        root=fields['K']&0xfffffffff000
        targets={'native_probe':0xfffffff0073ea0b0,'native_switch':0xfffffff0073ea10c,'vectors':0xfffffff0073ed000,'tracer':0xfffffff0073f1800}
        r['next_kernel_l3_reads']={name:{'va':hex(va),'index':(va>>12)&511,'entry_pa':hex(root+8*((va>>12)&511))} for name,va in targets.items()}
    r['interpretation']='Raw descriptor capture before TTBR replacement. An absent framebuffer entry prevents translation through that captured hierarchy; kernel execution still needs leaf/permission checks and a post-switch checkpoint.'
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    raw=json.loads(a.input.read_text())['numeric_fields'];r=analyze({k:int(v,0) for k,v in raw.items()});a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))

#!/usr/bin/env python3
"""Decode LEAF-B numeric PTE readbacks without claiming effective translation."""
import argparse,json
from pathlib import Path
TARGETS={'C':0xfffffff0073ea0b0,'H':0xfffffff0073f6214,'X':0xfffffff0073f1800,'V':0xfffffff0073ed000}

def analyze(fields):
    r={'snapshot':{k:hex(v) for k,v in fields.items()},'capture_complete':fields['S']==0,'post_switch_execution_verified':False,'effective_translation_verified':False,'future_stack_mapping_verified':False}
    if fields['S']!=0:
        r['note']='Some fields may be skipped-read placeholders; no leaf interpretation.'
        return r
    r['framebuffer_l2_absent']=not bool(fields['F']&1)
    if fields['K']&3!=3:raise ValueError('S=0 capture requires a kernel L3 table')
    out={}
    for name,va in TARGETS.items():
        d=fields[name];valid=d&3==3;pa=d&0xfffffffff000
        ref=(0x802e04000+va-0xfffffff007004000)&~0xfff
        out[name]={'va':hex(va),'raw':hex(d),'valid_L3_page':valid,'physical_page':hex(pa),'reference_bootstrap_physical_page':hex(ref),'matches_reference_page':valid and pa==ref,'access_flag':bool(d&(1<<10)),'ap':(d>>6)&3,'privileged_read_only':((d>>6)&3)==2,'attr_index':(d>>2)&7,'shareability':(d>>8)&3,'pxn':bool(d&(1<<53)),'uxn':bool(d&(1<<54)),'contiguous_hint':bool(d&(1<<52)),'el1_execution_allowed_by_leaf':valid and bool(d&(1<<10)) and not bool(d&(1<<53))}
    r['leaves']=out
    r['all_four_match_reference_and_allow_el1_at_leaf']=all(x['matches_reference_page'] and x['el1_execution_allowed_by_leaf'] for x in out.values())
    r['limits']=['Readbacks are from prepared tables before switching, not an effective translation test.','Hierarchical permissions and control registers also affect execution.','Contiguous hints require consistency of the full 16-PTE group; all members were not captured.','Stack and other data mappings are not captured by these four code PTEs.','Reference bootstrap physical/virtual bases are prior hardware observations, not newly measured fields in this photo.']
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();raw=json.loads(a.input.read_text())['numeric_fields'];r=analyze({k:int(v,0) for k,v in raw.items()});a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))

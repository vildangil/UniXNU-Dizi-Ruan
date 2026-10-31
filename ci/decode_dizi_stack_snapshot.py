#!/usr/bin/env python3
"""Decode STACK-B packed terminal levels/statuses without claiming live access."""
import argparse,json
from pathlib import Path

def analyze(fields):
    sp=fields['B'];targets={'P':sp-8,'Q':sp-384,'D':0xfffffff00716abb8,'M':0xfffffff00716c048};out={}
    for i,(name,va) in enumerate(targets.items()):
        status=(fields['S']>>(8*i))&255;level=(fields['L']>>(4*i))&15;ro=bool(fields['L']&(1<<(16+i)))
        d=fields[name];r={'va':hex(va),'status':status,'terminal_level':level,'ancestor_el1_readonly':ro,'raw':hex(d),'readback':status==0}
        if status==0:
            valid=(level in (1,2) and d&3==1) or (level==3 and d&3==3)
            r['valid_terminal_descriptor']=valid
            if valid:
                shift=12+9*(3-level);base=(d&0xfffffffff000)&~((1<<shift)-1);pa=base+(va&((1<<shift)-1));ap=(d>>6)&3;af=bool(d&(1<<10))
                r.update({'physical_address':hex(pa),'ap':ap,'access_flag':af,'attr_index':(d>>2)&7,'pxn':bool(d&(1<<53)),'uxn':bool(d&(1<<54)),'physical_address_fits_40bit':pa<(1<<40),'contiguous_hint':bool(d&(1<<52)),'writable_by_descriptor_and_ancestor_ap':ap<2 and not ro,'kernel_only_writable_evidence':af and ap==0 and not ro and pa<(1<<40)})
        out[name]=r
    return {'native_sp':hex(sp),'selected_stack_root_pa':hex(fields['R']),'targets':out,'effective_post_switch_access_verified':False,'same_physical_backing_as_current_stack_verified':False,'note':'Status 0 can report an actual invalid descriptor. Nonzero status means terminal read skipped. AF/AP and ancestor RO do not prove effective access: MAIR, PAN, contiguous-group consistency and other controls still matter. Valid future mappings do not prove preservation of the current physical stack backing.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();raw=json.loads(a.input.read_text())['numeric_fields'];r=analyze({k:int(v,0) for k,v in raw.items()});a.output.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))

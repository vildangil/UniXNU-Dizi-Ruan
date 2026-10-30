#!/usr/bin/env python3
"""Offline validation of photographed Dizi XNU walk-b descriptors.

Read-only: this is static interpretation of hardware-derived entries,
NOT a measurement of the first instruction after enabling MMU.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

MASK64=(1<<64)-1


def check(source:Path)->dict:
    info=json.loads(source.read_text())
    r={k:int(v,0) for k,v in info['registers'].items()}
    d={k:int(v,0) if isinstance(v,str) else v for k,v in info['descriptors'].items()}
    tcr=r['TCR_EL1']; ttbr1=r['TTBR1_EL1']; x22=r['X22']; x23=r['X23']
    t1sz=(tcr>>16)&0x3f
    vabits=64-t1sz
    assert (tcr>>30)&3==2, 'TG1 must be 4KiB'
    assert 31<=vabits<=39, 'Expected L1 start level for 4KiB granule'
    assert (tcr>>23)&1==0, 'TTBR1 page walk is disabled'
    assert d['STATUS']==2, 'This specific screenshot needs an L2 block'
    assert (d['L1']&3)==3, 'L1 does not contain a valid table descriptor'
    assert (d['L2']&3)==1, 'L2 is not a 2MiB block descriptor'
    l1_index_bits=vabits-30
    l1_pa=d['L1'] & 0x0000fffffffff000
    block_pa=d['L2'] & 0x0000ffffffe00000
    attrs={'access_flag':bool(d['L2']&(1<<10)),
           'privileged_execute_never':bool(d['L2']&(1<<53)),
           'user_execute_never':bool(d['L2']&(1<<54)),
           'attribute_index':(d['L2']>>2)&7,
           'access_permissions':(d['L2']>>6)&3,
           'shareability':(d['L2']>>8)&3}
    assert attrs['access_flag'], 'L2 access flag not set'
    assert not attrs['privileged_execute_never'], 'L2 blocks EL1 instruction fetch'
    output={
        'granule_bytes':4096,'ttbr1_virtual_address_bits':vabits,
        'l1_index_bits':l1_index_bits,
        'ttbr1_root_pa':hex(ttbr1),
        'l1_descriptor_pa':None,'l1_next_table_pa':hex(l1_pa),
        'l2_block_pa':hex(block_pa),'l2_attributes':attrs,
        'addresses':{},'fb_mapping_not_yet_measured':True,
        'mmu_enabled_confirmed':False,
    }
    for name,va in (('post_isb_pc',int(info['next_instruction_va'],0)),('vbar',r['VBAR_EL1'])):
        index1=(va>>30)&((1<<l1_index_bits)-1)
        index2=(va>>21)&511
        if output['l1_descriptor_pa'] is None:
            output['l1_descriptor_pa']=hex(ttbr1+index1*8)
        assert index1==0xc0 and index2==0x39, 'Unexpected observed L1/L2 indices'
        physical_from_l2=block_pa+(va&((1<<21)-1))
        physical_from_relocation=(x23+((va-x22)&MASK64))&MASK64
        assert physical_from_l2==physical_from_relocation, 'Descriptor and XNU relocation disagree'
        output['addresses'][name]={
            'virtual_address':hex(va),'l1_index':hex(index1),'l2_index':hex(index2),
            'physical_from_l2':hex(physical_from_l2),
            'physical_from_relocation':hex(physical_from_relocation),
            'agree':True,
        }
    fb_va=int(info['framebuffer_pa'],0)
    output['ttbr0_fb_test']={'va':hex(fb_va),'ttbr0_l1_index':hex((fb_va>>30)&((1<<l1_index_bits)-1)),
                             'ttbr0_l2_index':hex((fb_va>>21)&511)}
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=Path('data/dizi-walk-b-hardware-20261030.json'))
    args=p.parse_args()
    print(json.dumps(check(args.input),indent=2))

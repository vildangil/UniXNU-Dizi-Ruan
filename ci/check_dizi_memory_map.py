#!/usr/bin/env python3
"""Dizi offline memory/framebuffer/ADT source contradiction preflight.

Uses ONLY committed, redacted recovery observations and on-device screenshot
transcriptions. Does not touch physical device memory, UEFI runtime or GPIO.
Never treats Linux recovery reservations as a firmware allocation permit.
"""
from __future__ import annotations
import argparse,json,tomllib
from pathlib import Path

MIB=1024*1024
EXPECTED_RECOVERY_TOTAL=6061*MIB
EXPECTED_LEGACY_TOTAL=7944*MIB
EXPECTED_FB_PA=0xB8000000
EXPECTED_FB_RESERVED=43*MIB
EXPECTED_L2_ALIAS_VA=0xFFFFFFF004000000
EXPECTED_TABLE=0x802F70000

def contains(base:int,length:int,addr:int,amount:int)->bool:
    return base<=addr and amount>=0 and addr+amount<=base+length

def main(root:Path)->dict:
    data=json.loads((root/'data/dizi-fdt-observed.json').read_text())
    hw=json.loads((root/'config/dizi-hardware.json').read_text())
    walk=json.loads((root/'data/dizi-walk-b-hardware-20261030.json').read_text())
    slot=json.loads((root/'data/dizi-slot-b-hardware-20261031.json').read_text())
    fbwalk=json.loads((root/'data/dizi-fbwalk-b-hardware-20261031.json').read_text())
    deep=json.loads((root/'data/dizi-deep-b-arm-init-hardware-20261031.json').read_text())
    with (root/'board.toml').open('rb') as fh: board=tomllib.load(fh)
    obs=data['recovery_observation_2026_10_29']
    ram=[(int(r['base'],0),int(r['size'],0)) for r in obs['dtb_ram_banks_nonempty']]
    legacy=[(x['base'],x['size']) for x in data['memory_banks']]
    assert len(ram)==6 and len(legacy)==7, 'Recovery/legacy memory-bank count changed'
    assert sum(size for _,size in ram)==EXPECTED_RECOVERY_TOTAL, 'Unexpected physical-recovery RAM total'
    assert sum(size for _,size in legacy)==EXPECTED_LEGACY_TOTAL, 'Unexpected old reference-FDT RAM total'
    assert sum(size for _,size in ram)!=sum(size for _,size in legacy), 'Legacy map conflict disappeared'
    assert data['ram_candidate']['validated_on_device'] is False
    assert hw['ram_candidate']['validated_on_device'] is False
    assert board['board']['example'] is True
    assert board['payload']['kernel_args']==['-v','cpus=1']
    splash=obs['splash_region']
    splash_base,splash_size=int(splash['base'],0),int(splash['size'],0)
    assert (splash_base,splash_size)==(EXPECTED_FB_PA,EXPECTED_FB_RESERVED)
    assert contains(splash_base,splash_size,EXPECTED_FB_PA,2*MIB), 'Framebuffer alias crosses splash reservation'
    assert any(contains(base,size,EXPECTED_FB_PA,splash_size) for base,size in ram), 'Splash outside reported RAM'
    assert not any(contains(base,size,EXPECTED_FB_PA,2*MIB) for base,size in ((int(obs['ramoops']['base'],0),int(obs['ramoops']['size'],0)),)), 'Framebuffer overlaps ramoops'
    ttbr1=int(walk['registers']['TTBR1_EL1'],0)
    vbar=int(walk['registers']['VBAR_EL1'],0)
    l1=int(walk['descriptors']['L1'],0); l2=int(walk['descriptors']['L2'],0)
    assert l1&3==3 and (l1&0x0000fffffffff000)==EXPECTED_TABLE, 'L1 points somewhere unexpected'
    assert l2&3==1 and (l2&0x0000ffffffe00000)==0x803000000, 'Kernel executable block changed'
    assert all(any(contains(base,size,addr,4096) for base,size in ram)
               for addr in (ttbr1,EXPECTED_TABLE,0x802F6D000,0x803000000)), 'XNU tables/code not within recovery RAM bounds'
    assert int(slot['walk']['l1_descriptor'],0)==l1
    assert int(slot['walk']['proposed_alias_slot_l2_descriptor'],0)==0
    assert int(slot['walk']['candidate_alias_va'],0)==EXPECTED_L2_ALIAS_VA
    assert int(fbwalk['entries']['L1_DESC'],0)==0 and fbwalk['entries']['STATUS']==1
    assert 'ARM_INIT CPU0' in deep['observed_messages']
    assert obs['high_bank_1g']['completely_free_under_UEFI'] is False
    candidate=data['ram_candidate']
    cand_base,cand_len=candidate['base'],candidate['size']
    high_base=int(obs['high_bank_1g']['base'],0)
    reserved_from=int(obs['high_bank_1g']['first_runtime_reserved_addr'],0)
    assert cand_base==high_base and cand_len==0x40000000
    assert contains(cand_base,cand_len,reserved_from,1), 'Expected dynamic high-bank overlap not present'
    actual_fb_va=int(slot['walk']['candidate_alias_va'],0)
    assert actual_fb_va==EXPECTED_L2_ALIAS_VA
    output={
       'device':'dizi',
       'source_type':'offline recovery and photographed XNU snapshots only',
       'live_uefi_memory_ownership_validated':False,
       'recovery_ram_mib':sum(s for _,s in ram)//MIB,
       'legacy_reference_ram_mib':sum(s for _,s in legacy)//MIB,
       'legacy_reference_overstates_recovery_ram_mib':(EXPECTED_LEGACY_TOTAL-EXPECTED_RECOVERY_TOTAL)//MIB,
       'framebuffer_splash_pa':hex(splash_base),
       'framebuffer_splash_reservation_mib':splash_size//MIB,
       'guarded_high_alias_va':hex(EXPECTED_L2_ALIAS_VA),
       'guarded_alias_window_mib':2,
       'ttbr1_pa':hex(ttbr1),'l1_next_table_pa':hex(EXPECTED_TABLE),
       'kernel_l2_block_pa':hex(l2&0x0000ffffffe00000),
       'vbar_va':hex(vbar),
       'low_va_framebuffer_ttbr0_unmapped_before_sctlr':True,
       'high_bank_reference_candidate_not_firmware_safe':True,
       'high_bank_reserved_beginning_pa':hex(reserved_from),
       'ramoops_reserved_pa':obs['ramoops']['base'],
       'verified_current_hardware_checkpoint':'_arm_init CPU0 first opcode reached',
       'verified_allocator_or_rootfs_boot':False,
       'remaining_input':'UEFI runtime GetMemoryMap near ExitBootServices, ADT reserved ranges and device-native timer/GICR readbacks',
    }
    return output

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'))
    p.add_argument('--output',type=Path)
    opt=p.parse_args()
    r=main(opt.root)
    content=json.dumps(r,indent=2)+'\n'
    if opt.output:
        opt.output.parent.mkdir(parents=True,exist_ok=True)
        opt.output.write_text(content)
    print(content)

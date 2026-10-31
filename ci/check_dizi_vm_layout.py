#!/usr/bin/env python3
"""Offline layout audit of exact photographed FLOW-B. Not runtime qualification."""
import argparse,json,struct
from pathlib import Path
import patch_dizi_mmu_flow_b as f

def audit(path):
    boot=path.read_bytes()
    if f.sha(boot)!=f.OUTPUT_BOOT:raise ValueError('Expected pinned FLOW-B boot')
    b=boot[f.MACHO_OFF:f.MACHO_OFF+f.MACHO_BYTES]
    if f.sha(b)!=f.OUTPUT_MACHO:raise ValueError('Mach-O hash mismatch')
    count,size=struct.unpack_from('<II',b,16);p=32;segments=[]
    for _ in range(count):
        c,n=struct.unpack_from('<II',b,p)
        if n<8 or p+n>32+size:raise ValueError('Load-command bounds')
        if c==0x19:
            name,va,vs,fo,fs=struct.unpack_from('<16sQQQQ',b,p+8)
            if fs>vs or fo+fs>len(b) or va+vs>1<<64:raise ValueError('Segment bounds')
            segments.append(dict(name=name.rstrip(b'\0').decode(),va=va,vmsize=vs,fileoff=fo,filesize=fs))
        p+=n
    if p!=32+size:raise ValueError('Command size mismatch')
    occupied=sorted((x['va'],x['va']+x['vmsize'],x['name']) for x in segments if x['vmsize'])
    for a,z in zip(occupied,occupied[1:]):
        if a[1]>z[0]:raise ValueError('Virtual segment overlap')
    byname={x['name']:x for x in segments}
    for name in ('__TEXT','__TEXT_EXEC','__DATA','__DATA_CONST','__BOOTDATA','__PRELINK_TEXT','__PLK_TEXT_EXEC','__PRELINK_INFO'):
        if name not in byname or not byname[name]['vmsize']:raise ValueError('Missing '+name)
    alias=0xfffffff004000000;end=alias+0x200000
    if any(alias<b and a<end for a,b,_ in occupied):raise ValueError('Alias collides with Mach-O')
    nearest=min(a for a,_,_ in occupied if a>=end)
    return {'input_boot_sha256':f.OUTPUT_BOOT,'macho_sha256':f.OUTPUT_MACHO,'segment_count':len(segments),'segment_file_bounds_and_virtual_nonoverlap_pass':True,'segments':segments,'framebuffer_alias':hex(alias),'alias_bytes':0x200000,'alias_collides_with_macho':False,'gap_after_alias_before_next_segment_bytes':nearest-end,'vm_switch_ttbr1_call':'0xFFFFFFF0073EA10C','vm_switch_ttbr0_call':'0xFFFFFFF0073EA120','runtime_boot_args_values_validated':False,'runtime_efi_memory_ownership_validated':False,'fixups_or_kext_runtime_qualified':False,'new_tables_preserve_framebuffer_alias':None,'limitation':'File layout checks do not establish valid live memory ownership, boot_args, relocations, platform drivers, or post-switch framebuffer mapping'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();r=audit(a.input);a.output.write_text(json.dumps(r,indent=2)+'\n');print('PASS: pinned Mach-O segment bounds/nonoverlap and alias separation')

#!/usr/bin/env python3
"""Execute real table probe and native phystokv in bounded synthetic fixtures.

No hardware MMU/cache/interrupt validation. Does not replace device table reads.
"""
import argparse,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import *
import patch_dizi_mmu_table_b as m
from check_dizi_init_b_emulation import REGS,FB
f=m.flow
ROOT=0x804191000; CHILD=ROOT+0x1000; VIRT=0xfffffff00c191000
META=0xfffffff00716c000;PHI=0xfffffff0073e8784;TCR=0x22a51a251a

def run(kernel,site,op,traced,flags,case):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(f.CAVE&~0xfff,0x1000);u.mem_write(f.CAVE,kernel[f.off(kernel,f.CAVE):f.off(kernel,f.CAVE_END)])
    u.mem_map(site&~0xfff,0x2000);u.mem_write(site,kernel[f.off(kernel,site):f.off(kernel,site)+4] if traced else struct.pack('<I',op))
    u.mem_map(PHI&~0xfff,0x1000);u.mem_write(PHI,kernel[f.off(kernel,PHI):f.off(kernel,PHI)+0x194])
    for addr,size in [(0x200000,0x40000),(0x300000,0x10000),(FB,0x200000),(META,0x1000),(META-0x2000,0x1000),(VIRT,0x2000)]:u.mem_map(addr,size)
    u.mem_write(FB,b'\x33'*0x200000)
    for i,r in enumerate(REGS):u.reg_write(r,0x200000+i*0x1000)
    if site==m.SITES[-1][1]:u.reg_write(UC_ARM64_REG_X8,ROOT)
    u.reg_write(UC_ARM64_REG_SP,0x308000);u.reg_write(UC_ARM64_REG_NZCV,flags)
    tcr=TCR if case!='tcr' else TCR^1;u.cpr_write(3,0,2,0,2,tcr)
    vptr=VIRT+1 if case=='pointer' else VIRT
    desc=0 if case=='invalid_l1' else 0x803000601 if case=='block_l1' else ((ROOT-0x1000)|3 if case=='child_low' else (CHILD+0x2000)|3 if case=='child_high' else CHILD|3)
    fbdesc=0x00600000b8000c0d if case=='mapped_fb' else 0
    u.mem_write(0xfffffff00716abb0,struct.pack('<QQ',vptr,ROOT))
    u.mem_write(VIRT+0x600,struct.pack('<Q',desc))
    u.mem_write(VIRT+0x1100,struct.pack('<Q',fbdesc));u.mem_write(VIRT+0x11c8,struct.pack('<Q',0x803000601))
    u.mem_write(META+0x108,struct.pack('<QQQ',0x800000000,0x10000000,0x200000 if case=='converted_pointer' else 0xfffffff008000000))
    u.mem_write(META+0x138,struct.pack('<Q',CHILD+0x2000))
    if case=='range_mapping':u.mem_write(META+0x48,struct.pack('<QQQ',ROOT,VIRT,0x4000))
    before=bytes(u.mem_read(0x200000,0x40000));lines=[];writes=[]
    def write(uc,access,address,size,value,data):
        assert FB<=address and address+size<=FB+0x200000 or 0x307ec0<=address and address+size<=0x308000,hex(address)
        if address==0x307ed2 and size==1 and value==0:lines.append(bytes(uc.mem_read(0x307ec0,18)).decode('ascii'))
        writes.append((address,size))
    u.hook_add(UC_HOOK_MEM_WRITE,write)
    u.emu_start(site,site+4,count=1000000 if traced else 1)
    assert u.reg_read(UC_ARM64_REG_PC)==site+4
    assert bytes(u.mem_read(0x200000,0x40000))==before
    # Neither table page nor native mapping metadata may be modified.
    assert struct.unpack('<Q',u.mem_read(VIRT+0x600,8))[0]==desc
    state=[u.reg_read(x) for x in REGS]+[u.reg_read(UC_ARM64_REG_SP),u.reg_read(UC_ARM64_REG_NZCV)]
    if traced:
        assert any(FB<=a<FB+0x200000 for a,_ in writes)
        if site==m.SITES[-1][1]:
            status={'tcr':1,'pointer':2,'invalid_l1':3,'block_l1':3,'child_low':4,'child_high':4,'converted_pointer':5}.get(case,0)
            vals=[ROOT,0 if status==1 else vptr,0 if status in (1,2) else desc,0 if status in (1,2,3) else desc&0xfffffffff000,fbdesc if status==0 else 0,0x803000601 if status==0 else 0,status,tcr]
            expected=[f'{n} {v:016X}' for n,v in zip('NVLPFKST',vals)]
            assert lines==expected,(case,lines,expected)
    return state

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    b=a.input.read_bytes();assert f.sha(b)==m.OUTPUT_BOOT;k=b[f.MACHO_OFF:f.MACHO_OFF+f.MACHO_BYTES]
    count=0;cases=['absent_fb','mapped_fb','range_mapping','tcr','pointer','invalid_l1','block_l1','child_low','child_high','converted_pointer']
    for case in cases:
        for _,site,op in m.SITES:
            for flags in [0,0xf0000000,0xa0000000,0x50000000]:
                assert run(k,site,op,False,flags,case)==run(k,site,op,True,flags,case),(case,hex(site))
                count+=1
    r={'emulator':'unicorn 2.1.4','native_vs_hook_cases_passed':count,'fixtures':cases,'real_native_phystokv_executed':True,'descriptor_and_status_strings_checked':True,'page_table_writes_permitted':False,'hardware_tested':False,'limitations':'Synthetic memory/translation metadata; no real MMU/Device/cache/IRQ validation'};a.output.write_text(json.dumps(r,indent=2)+'\n');print('PASS:',count,'table probe comparisons with exact numeric strings and read-only memory bounds')
if __name__=='__main__':main()

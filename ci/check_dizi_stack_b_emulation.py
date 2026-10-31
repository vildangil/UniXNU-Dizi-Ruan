#!/usr/bin/env python3
"""Compare native state and real walker strings against a separate host walk."""
import argparse,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import *
import patch_dizi_mmu_stack_b as m
from check_dizi_init_b_emulation import REGS,FB
f=m.flow
ROOT0=0x804190000; ROOT1=ROOT0+0x1000; VB=0xfffffff00c190000
META=0xfffffff00716c000;GLOBALS=0xfffffff00716aba0;PHI=0xfffffff0073e8784;TCR=0x22a51a251a

def run(kernel,site,op,traced,flags,case):
    sp=0xfffffff007bb3e00 if case=='high_stack' else 0xfffffff007bb3080 if case=='cross_page' else 0x4000308000 if case=='noncanonical_stack' else 0x308000
    targets=[sp-8,sp-384,GLOBALS+24,META+0x48]
    pages={ROOT0:bytearray(4096),ROOT1:bytearray(4096)};nextpa=ROOT1+0x1000
    def alloc():
        nonlocal nextpa
        p=nextpa;nextpa+=4096;pages[p]=bytearray(4096);return p
    def put(pa,idx,d):struct.pack_into('<Q',pages[pa],idx*8,d)
    def get(pa,idx):return struct.unpack_from('<Q',pages[pa],idx*8)[0]
    for i,va in enumerate(targets):
        if va>>38 not in (0,(1<<26)-1):continue
        root=ROOT0 if va>>38==0 else ROOT1;pa=root
        for level in (1,2):
            idx=(va>>(12+9*(3-level)))&(255 if level==1 else 511)
            d=get(pa,idx)
            if d==0:d=alloc()|3;put(pa,idx,d)
            pa=d&0xfffffffff000
        idx=(va>>12)&511
        raw=0x0060000805000603+((va>>12)&511)*4096
        if case=='stack_readonly' and i<2:raw|=0x80
        if case=='missing_stack' and i<2:raw=0
        if case=='missing_data' and i==2:raw=0
        put(pa,idx,raw)
    if case=='ancestor_readonly':
        for root in (ROOT0,ROOT1):
            for idx in range(256):
                d=get(root,idx)
                if d:put(root,idx,d|(1<<62))
    if case=='l2_block':
        for va in targets:
            if va>>38 not in (0,(1<<26)-1):continue
            root=ROOT0 if va>>38==0 else ROOT1
            child=get(root,(va>>30)&255)&0xfffffffff000
            put(child,(va>>21)&511,0x0060000804000601)
    free=nextpa
    if case=='child_bounds':
        for root in (ROOT0,ROOT1):
            for idx in range(256):
                if get(root,idx):put(root,idx,(free+0x1000)|3)
    rootva={ROOT0:VB,ROOT1:VB+0x1000}
    if case=='root0_pointer':rootva[ROOT0]+=1
    if case=='root1_pointer':rootva[ROOT1]+=1
    def reference(va):
        if case=='bad_tcr':return 0,1,0,0,0
        top=va>>38
        if top not in (0,(1<<26)-1):return 0,2,1,0,0
        root=ROOT0 if top==0 else ROOT1
        if rootva[root]&4095:return 0,3,1,root,0
        pa=root;ro=0
        for level in (1,2,3):
            idx=(va>>(12+9*(3-level)))&(255 if level==1 else 511)
            d=get(pa,idx)
            if level==3 or d&3!=3:return d,0,level,root,ro
            ro|=(d>>62)&1
            child=d&0xfffffffff000
            if not ROOT0<=child or child+4096>free:return 0,4,level,root,ro
            if case=='converted_pointer':return 0,5,level,root,ro
            pa=child
        raise AssertionError('unreachable')
    expected=[reference(v) for v in targets]
    levels=sum((x[2]<<(4*i))|(x[4]<<(16+i)) for i,x in enumerate(expected))
    statuses=sum(x[1]<<(8*i) for i,x in enumerate(expected))
    values=[sp]+[x[0] for x in expected]+[levels,expected[0][3],statuses]
    want=[f'{n} {v:016X}' for n,v in zip('BPQDMLRS',values)]
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(f.CAVE&~4095,4096);u.mem_write(f.CAVE,kernel[f.off(kernel,f.CAVE):f.off(kernel,f.CAVE_END)])
    u.mem_map(site&~4095,8192);u.mem_write(site,kernel[f.off(kernel,site):f.off(kernel,site)+4] if traced else struct.pack('<I',op))
    u.mem_map(PHI&~4095,4096);u.mem_write(PHI,kernel[f.off(kernel,PHI):f.off(kernel,PHI)+0x194])
    for addr,size in [(0x200000,0x40000),(sp&~4095,4096),(FB,0x200000),(META,4096),(GLOBALS&~4095,4096),(VB,0x40000)]:u.mem_map(addr,size)
    if sp&4095<384:u.mem_map((sp&~4095)-4096,4096)
    u.mem_write(FB,b'\x33'*0x200000)
    for i,r in enumerate(REGS):u.reg_write(r,0x200000+i*4096)
    u.reg_write(UC_ARM64_REG_SP,sp);u.reg_write(UC_ARM64_REG_NZCV,flags)
    u.cpr_write(3,0,2,0,2,TCR^1 if case=='bad_tcr' else TCR)
    for pa,data in pages.items():u.mem_write(VB+pa-ROOT0,bytes(data))
    u.mem_write(GLOBALS,struct.pack('<4Q',rootva[ROOT0],ROOT0,rootva[ROOT1],ROOT1))
    u.mem_write(META+0x108,struct.pack('<3Q',0x800000000,0x10000000,0x200000 if case=='converted_pointer' else 0xfffffff008000000))
    u.mem_write(META+0x138,struct.pack('<Q',free))
    if case=='range_mapping':u.mem_write(META+0x48,struct.pack('<3Q',ROOT0,VB,free-ROOT0))
    lines=[];count=0
    def write(uc,access,addr,size,value,data):
        nonlocal count
        assert FB<=addr and addr+size<=FB+0x200000 or sp-384<=addr and addr+size<=sp,hex(addr)
        count+=1
        if addr==sp-384+18 and size==1 and value==0:lines.append(bytes(uc.mem_read(sp-384,18)).decode('ascii'))
    u.hook_add(UC_HOOK_MEM_WRITE,write)
    u.emu_start(site,site+4,count=1000000 if traced else 1)
    assert u.reg_read(UC_ARM64_REG_PC)==site+4
    if traced:
        assert count>0
        if site==m.SITES[-1][1]:assert lines==want,(case,lines,want)
    return [u.reg_read(r) for r in REGS]+[u.reg_read(UC_ARM64_REG_SP),u.reg_read(UC_ARM64_REG_NZCV)]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    b=a.input.read_bytes();assert f.sha(b)==m.OUTPUT_BOOT;k=b[f.MACHO_OFF:f.MACHO_OFF+f.MACHO_BYTES]
    cases=['low_stack','high_stack','cross_page','stack_readonly','missing_stack','missing_data','ancestor_readonly','l2_block','root0_pointer','root1_pointer','bad_tcr','child_bounds','converted_pointer','noncanonical_stack','range_mapping'];count=0
    for case in cases:
        for _,site,op in m.SITES:
            for flags in (0,0xf0000000,0xa0000000,0x50000000):
                assert run(k,site,op,False,flags,case)==run(k,site,op,True,flags,case),(case,hex(site));count+=1
    r={'emulator':'unicorn 2.1.4','native_vs_hook_cases_passed':count,'fixtures':cases,'real_native_phystokv_executed':True,'independent_python_walk_reference':True,'exact_numeric_rows_verified':True,'table_writes_permitted':False,'hardware_tested':False,'limitations':'Synthetic roots/mappings; no effective hardware MMU/cache/IRQ validation'};a.output.write_text(json.dumps(r,indent=2)+'\n');print('PASS:',count,'stack/data walk comparisons including both roots, block/invalid terminals and inherited RO')
if __name__=='__main__':main()

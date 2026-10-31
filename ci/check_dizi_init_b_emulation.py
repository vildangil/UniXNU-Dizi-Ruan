#!/usr/bin/env python3
"""Compare all INIT-B hook effects against each displaced native instruction.

Host CPU emulation only: does not model MMU, Device memory, IRQs or hardware.
Requires unicorn==2.1.4. Stops before executing native BL callees.
"""
import argparse,json,struct
from pathlib import Path
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import *
import patch_dizi_mmu_init_b as init
f=init.flow
REGS=[UC_ARM64_REG_X0+i for i in range(29)]+[UC_ARM64_REG_X29,UC_ARM64_REG_X30]
FB=0xfffffff004000000

def run(kernel,site,opcode,traced,flags):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(f.CAVE&~0xfff,0x1000)
    u.mem_write(f.CAVE,kernel[f.off(kernel,f.CAVE):f.off(kernel,f.CAVE_END)])
    u.mem_map(site&~0xfff,0x2000)
    u.mem_write(site,struct.pack('<I',opcode) if not traced else kernel[f.off(kernel,site):f.off(kernel,site)+4])
    u.mem_map(0x200000,0x40000);u.mem_map(0x300000,0x10000);u.mem_map(FB,0x200000)
    u.mem_write(FB,b'\x33'*0x200000)
    for i,r in enumerate(REGS): u.reg_write(r,0x200000+i*0x1000)
    u.reg_write(UC_ARM64_REG_SP,0x308000);u.reg_write(UC_ARM64_REG_NZCV,flags)
    pixels=[]
    def write(uc,access,address,size,value,data):
        if FB<=address<FB+0x200000: pixels.append((address,size))
        else:
            assert 0x200000<=address<0x240000 or 0x307f40<=address<0x308000,hex(address)
    u.hook_add(UC_HOOK_MEM_WRITE,write)
    stop=site+4
    if opcode>>26==0x25: stop=site+init.signed(opcode&0x3ffffff,26)*4
    if traced: u.emu_start(site,stop,count=1000000)
    else: u.emu_start(site,stop,count=1)
    assert u.reg_read(UC_ARM64_REG_PC)==stop, 'Hook failed to reach native continuation'
    if traced and init.__name__=='patch_dizi_mmu_vm_b' and site==init.SITES[0][1]:
        assert bytes(u.mem_read(FB,16))==bytes(16), 'Stale top pixels not cleared'
        assert bytes(u.mem_read(FB+0x200000-16,16))==bytes(16), 'Clear did not cover full alias'
        assert any(u.mem_read(FB,0x200000)), 'Marker missing after clear'
    return [u.reg_read(r) for r in REGS]+[u.reg_read(UC_ARM64_REG_SP),u.reg_read(UC_ARM64_REG_NZCV)],bytes(u.mem_read(0x200000,0x40000)),pixels

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--variant',choices=['init-b','vm-b'],default='init-b');a=p.parse_args()
    global init
    if a.variant=='vm-b':
        import patch_dizi_mmu_vm_b as vm
        init=vm
    boot=a.input.read_bytes();assert f.sha(boot)==init.OUTPUT_BOOT
    kernel=boot[f.MACHO_OFF:f.MACHO_OFF+f.MACHO_BYTES]
    cases=[]
    for name,site,opcode in init.SITES:
        for flags in (0,0xf0000000,0xa0000000,0x50000000):
            reference=run(kernel,site,opcode,False,flags);actual=run(kernel,site,opcode,True,flags)
            assert reference[:2]==actual[:2],(name,hex(flags),'native state differs')
            assert actual[2], 'No pixels drawn'
            assert max(x+n for x,n in actual[2])<=FB+0x200000
        cases.append({'stage':name,'nzcv_patterns':4,'registers_sp_flags_native_store_and_return_match':True})
    out={'emulator':'unicorn 2.1.4','cases_passed':len(cases)*4,'hardware_tested':False,'cases':cases,'limitations':'No hardware MMU/cache/IRQ/Device mapping validation; no native callee execution'}
    a.output.write_text(json.dumps(out,indent=2)+'\n');print('PASS:',len(cases)*4,'native-vs-hook state comparisons')
if __name__=='__main__':main()

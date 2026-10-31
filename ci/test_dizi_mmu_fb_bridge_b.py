#!/usr/bin/env python3
"""Offline negative/positive test of SHA-pinned framebuffer TTBR bridge.

This does not emulate or validate physical post-MMU behavior.
"""
import argparse,hashlib,struct,tempfile
from pathlib import Path
import patch_dizi_mmu_fb_bridge_b as b

def main(src:Path,output:Path):
    image=output.read_bytes();original=src.read_bytes()
    assert b.sha(image)==b.OUTPUT_BOOT and b.sha(original)==b.INPUT_BOOT
    before=original[b.MACHO_OFF:b.MACHO_OFF+b.MACHO_LEN]
    after=image[b.MACHO_OFF:b.MACHO_OFF+b.MACHO_LEN]
    c=b.off(after,b.CAVE)
    permitted=set(range(c,c+b.CAVE_SIZE))
    for addr,op in b.OLD_HOOKS:
        off=b.off(before,addr)
        permitted.update(range(off,off+4))
        # All earlier native VM hooks except pre-switch have been undone.
        if addr!=b.PRE:assert struct.unpack_from('<I',after,off)[0]==op
    for site,target in ((b.PRE,b.CAVE),(b.POST,b.CAVE+28)):
        off=b.off(before,site)
        permitted.update(range(off,off+4))
        assert struct.unpack_from('<I',after,off)[0]==b.branch(site,target)
    changed=[i for i,(old,new) in enumerate(zip(before,after)) if old!=new]
    assert changed and all(i in permitted for i in changed)
    assert image[:b.MACHO_OFF]==original[:b.MACHO_OFF]
    assert image[b.MACHO_OFF+b.MACHO_LEN:]==original[b.MACHO_OFF+b.MACHO_LEN:]
    # Native privileged TTBR1/TTBR0/TLBI/barrier sequence remains untouched.
    for addr in (0xfffffff0073ea10c,0xfffffff0073ea120,0xfffffff0073ea124,0xfffffff0073ea128,0xfffffff0073ea12c):
        off=b.off(before,addr)
        assert after[off:off+4]==before[off:off+4]
    assert struct.unpack_from('<5I',after,b.off(after,0xfffffff0073ea11c))==b.EXPECTED_MMU
    cave=after[c:c+b.CAVE_SIZE]
    assert b.sha(cave[:1463])==b.TRACE_SHA and not any(cave[1463:])
    # The AArch64-only descriptor store is exactly STR X5,[X19,#0x100]
    # and must be preceded by equality checks, followed by DSB ISHST/readback.
    words=[struct.unpack_from('<I',cave,i)[0] for i in range(0,1460,4)]
    assert words.count(0xf9008265)==1
    assert words.count(0xd5033a9f)==1
    assert 0xd4000003 not in words # No SMC
    assert not any(w & 0xffe0001f==0xd5000000 for w in words) # no direct TTBR writes
    # Independently decode BOTH relocated ADRPs and native return branches.
    def adrp_target(pc:int,op:int)->int:
        assert op & 0x9f000000 == 0x90000000
        imm=((op>>29)&3)|(((op>>5)&0x7ffff)<<2)
        if imm&(1<<20):imm-=1<<21
        return (pc&~0xfff)+(imm<<12)
    for local,origin in ((20,b.PRE),(48,b.POST)):
        assert adrp_target(b.CAVE+local,struct.unpack_from('<I',cave,local)[0])==0xfffffff00716c000
        assert struct.unpack_from('<I',cave,local+4)[0]==b.branch(b.CAVE+local+4,origin+4)
    for msg in (b'FB ALIAS READY\x00',b'FB NEW TTBR OK\x00',b'FBFAIL1\x00',b'FBFAIL9\x00'):
        assert msg in cave
    # Reject any wrong input, even a one-bit difference.
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        tampered=bytearray(original);tampered[-1]^=1
        (root/'tampered.img').write_bytes(tampered)
        try:b.build(root/'tampered.img',root/'output.img',root/'audit.json')
        except ValueError as ex:assert 'STACK-B' in str(ex)
        else:raise AssertionError('Corrupted boot accepted')
    print('PASS: exact hashes, five hook locations, one L2 store, native TTBR sequence, zero-change outside allowlist, corrupt input rejection')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    main(a.input,a.output)

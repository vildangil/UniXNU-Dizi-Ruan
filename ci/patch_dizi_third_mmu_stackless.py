#!/usr/bin/env python3
"""Dizi: third-only stackless MMU checkpoint in a SHA-pinned Mach-O COPY.

For A/B testing against first-TWO-NOSP hardware: identical prior stages,
replace only the third (GOLD Y456) 84-byte trampoline. Replays its original
0xAA010000 instruction and branches to the original next instruction.
This is an invasive diagnostic: x9-x11/NZCV are clobbered, no MMU boot proof.
"""
import argparse, hashlib, json, struct
from pathlib import Path

SOURCE_SHA='d88862b4d30fd444ad46ab7d876c2f716b1e745a3875fce885e34b1b823430d1'
MARK='DIZI_THIRD_MMU_STAGE_STACKLESS_V1'
ENTRY=0xFFFFFFF0073F0488
SECOND_STUB=ENTRY+0x254
THIRD_STUB=ENTRY+0x2A8
FOURTH_STUB=ENTRY+0x2FC
THIRD_HOOK=0xFFFFFFF0073F22FC
THIRD_ORIGINAL=0xAA010000
TTBR1=0xFFFFFFF0073F22B8
SCTLR=0xFFFFFFF0073F2350

def arm_b(source,target):
    distance=target-source
    if distance%4 or not -(1<<27)<=distance<(1<<27):
        raise ValueError('ARM64 branch not reachable')
    return 0x14000000|((distance>>2)&0x3FFFFFF)

def offset(data,va):
    if len(data)<4096 or struct.unpack_from('<I',data)[0]!=0xFEEDFACF:
        raise ValueError('Not Mach-O64')
    n,cmd_len=struct.unpack_from('<II',data,16)
    if not 0<n<256 or cmd_len>len(data)-32:
        raise ValueError('Invalid Mach-O load commands')
    pos=32
    for _ in range(n):
        cmd,size=struct.unpack_from('<II',data,pos)
        if size<8 or pos+size>len(data):
            raise ValueError('Corrupt Mach-O load command')
        if cmd==0x19:
            name,addr,vm_size,file_off,file_size=struct.unpack_from('<16sQQQQ',data,pos+8)
            if name.rstrip(b'\x00')==b'__TEXT_EXEC' and addr<=va<addr+min(vm_size,file_size):
                out=file_off+va-addr
                if out+4>len(data):raise ValueError('Truncated Mach-O')
                return out
        pos+=size
    raise ValueError('VA not file-backed __TEXT_EXEC: '+hex(va))

def patch(source,output,report):
    if source.resolve()==output.resolve():raise ValueError('Refusing in-place edit')
    data=bytearray(source.read_bytes())
    sha=hashlib.sha256(data).hexdigest()
    if sha!=SOURCE_SHA:raise ValueError('Incorrect pinned first-TWO-NOSP input SHA: '+sha)
    second,third,fourth=(offset(data,x) for x in (SECOND_STUB,THIRD_STUB,FOURTH_STUB))
    if third-second!=84 or fourth-third!=84:raise ValueError('Unexpected cave span')
    second_words=struct.unpack_from('<11I',data,second)
    if second_words[:3]!=(0xD2860009,0xF2B70549,0x5288A00A) or second_words[9]!=0xAA1F03E0:
        raise ValueError('Pinned second no-SP probe mismatch')
    if struct.unpack_from('<I',data,third)[0]!=0xD100C3FF:
        raise ValueError('Original third stack-based probe absent')
    if struct.unpack_from('<I',data,fourth)[0]!=0xD100C3FF:
        raise ValueError('Fourth stack-based probe changed')
    hook=offset(data,THIRD_HOOK)
    if struct.unpack_from('<I',data,hook)[0]!=arm_b(THIRD_HOOK,THIRD_STUB):
        raise ValueError('Third hook no longer reaches third cave')
    if struct.unpack_from('<I',data,offset(data,TTBR1))[0]!=0xD5182020:
        raise ValueError('Original TTBR1 MSR changed')
    if struct.unpack_from('<II',data,offset(data,SCTLR))!=(0xD5181000,0xD5033FDF):
        raise ValueError('Original SCTLR and ISB changed')
    # First nine words are the byte-validated direct-GOP sequence used by
    # the hardware-verified first and second no-SP probes. No SP access.
    instructions=list(second_words[:9])
    instructions[:4]=[0xD2910009,0xF2B70589,0x529AE00A,0x72BFFFEA]
    instructions.extend([THIRD_ORIGINAL,arm_b(THIRD_STUB+40,THIRD_HOOK+4)])
    payload=struct.pack('<11I',*instructions)
    if len(payload)!=44 or instructions[8]!=0xD5033F9F:
        raise ValueError('Invalid stackless trampoline template')
    payload+=struct.pack('<I',0xD503201F)*10
    if len(payload)!=84:raise ValueError('Incorrect padded payload size')
    old=bytes(data)
    data[third:fourth]=payload
    if data[:third]!=old[:third] or data[fourth:]!=old[fourth:] or len(data)!=len(old):
        raise AssertionError('Modification escaped third marker reservation')
    if struct.unpack_from('<I',data,offset(data,TTBR1))[0]!=0xD5182020:
        raise AssertionError('TTBR1 changed')
    if struct.unpack_from('<II',data,offset(data,SCTLR))!=(0xD5181000,0xD5033FDF):
        raise AssertionError('SCTLR/ISB changed')
    diff=sum(x!=y for x,y in zip(old,data))
    if not diff:raise AssertionError('No changes')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(data)
    info={'marker':MARK,'source_sha256':sha,
          'patched_sha256':hashlib.sha256(data).hexdigest(),
          'bytes':len(data),'changed_byte_count':diff,
          'modified_region_bytes':84,'third_stub_va':hex(THIRD_STUB),
          'third_hook_va':hex(THIRD_HOOK),'return_va':hex(THIRD_HOOK+4),
          'third_gold_y':[456,464],
          'only_third_checkpoint_modified':True,
          'first_two_no_sp_checkpoint_bytes_preserved':True,
          'remaining_three_stack_based_stubs_preserved':True,
          'native_ttbr1_sctlr_isb_untouched':True,
          'source_untouched':True,'mmu_enabled_on_hardware':False,
          'meaning':'GOLD Y456 proves third hook reached before MAIR; not XNU MMU enable'}
    report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps(info,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    patch(args.input,args.output,args.report)

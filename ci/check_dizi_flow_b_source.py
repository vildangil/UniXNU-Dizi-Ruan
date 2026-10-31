#!/usr/bin/env python3
"""Verify FLOW-B auditable AArch64 assembly reproduces pinned binary payload.

This is a build-time check only. Reads arch-b Mach-O for the exact known
5x7 font, compiles the assembly, patches NOP return jumps and compares
all bytes to the versioned payload. Does not modify the input image.
"""
from __future__ import annotations
import argparse,base64,hashlib,struct,shutil,subprocess,tempfile
from pathlib import Path
import patch_dizi_mmu_flow_b as flow
FONT_SHA='71d8475b427a59edaca1ad55592e83812e7fe5c7f8be8444ffc1d3733d303501'

def verify(input_img:Path)->dict:
    boot=input_img.read_bytes()
    if len(boot)!=flow.BOOT_BYTES or flow.sha(boot)!=flow.SOURCE_BOOT:
        raise ValueError('Expected pinned physical arch-b boot image')
    macho=boot[flow.MACHO_OFF:flow.MACHO_OFF+flow.MACHO_BYTES]
    font_pos=flow.off(macho,0xfffffff0073f0d90)
    font=macho[font_pos:font_pos+413]
    if flow.sha(font)!=FONT_SHA:raise ValueError('Unexpected font payload')
    src=Path(__file__).with_name('dizi_mmu_flow_b.S.in').read_text()
    if src.count('FONT_DATA')!=1:raise ValueError('Assembly placeholder changed')
    src=src.replace('FONT_DATA','.byte '+','.join(str(x) for x in font))
    clang=shutil.which('clang-18') or shutil.which('clang')
    objcopy=shutil.which('llvm-objcopy-18') or shutil.which('llvm-objcopy')
    if not clang or not objcopy or not shutil.which('readelf'):
        raise RuntimeError('LLVM assembler, llvm-objcopy, readelf required')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)
        (p/'flow.S').write_text(src)
        subprocess.run([clang,'--target=aarch64-none-elf','-c',str(p/'flow.S'),'-o',str(p/'flow.o')],check=True)
        reloc=subprocess.check_output(['readelf','-r',str(p/'flow.o')],text=True)
        if 'There are no relocations in this file' not in reloc:
            raise ValueError('Unexpected AArch64 relocations')
        subprocess.run([objcopy,'-O','binary','-j','.text.trace',str(p/'flow.o'),str(p/'flow.bin')],check=True)
        code=bytearray((p/'flow.bin').read_bytes())
    if len(code)!=1163:raise ValueError('Unexpected assembly byte count')
    for i,(_,site,native) in enumerate(flow.SITES):
        resume=i*28+16
        if struct.unpack_from('<II',code,resume)!=(0xa8c137ec,native):
            raise ValueError('Displaced native instruction changed')
        if struct.unpack_from('<I',code,resume+8)[0]!=0xd503201f:
            raise ValueError('Missing branch slot')
        struct.pack_into('<I',code,resume+8,flow.branch(flow.CAVE+resume+8,site+4))
    payload=base64.b64decode(Path(__file__).with_name('dizi_mmu_flow_b_payload.b64').read_text().strip(),validate=True)
    if bytes(code)!=payload or flow.sha(payload)!=flow.PAYLOAD_SHA:
        raise ValueError('Readable assembly does not match pinned payload')
    return {'source_validated':True,'aarch64_bytes':len(code),'payload_sha256':flow.sha(code),'native_return_targets_checked':len(flow.SITES)}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    opts=parser.parse_args()
    print(verify(opts.input))

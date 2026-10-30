#!/usr/bin/env python3
"""SHA-pinned read-only Dizi pre-SCTLR page-table diagnostic. fastboot boot ONLY."""
import argparse,base64,hashlib,json,struct
from pathlib import Path
import patch_dizi_post_mmu_b as c
import patch_dizi_text_console_b as t

SOURCE='ccb3c22f680aa67aac58669f77c051e4784e253e7965baf3a93feb8e38374a0b'
KERNEL='a6222120639cc2fb39b5d3e353b623253d3cd9f58dd006685b95b8f1948f65eb'
PAYLOAD='1ccb26e8ffd9c68937cb6f9a8efc17ee4c654b269e730db6541fb06edf4153f7'
OUTPUT='8c5c1aba446897a7548461a05718d79ddfb5607cfd0745c5187d423ed3a05542'
OUT_KERNEL='00e522094ba5981f3520279f5b33611cfce1aac17f1156ab2b6b6362aaa30270'
sha=lambda b:hashlib.sha256(b).hexdigest()

def build(src,dst,audit):
    if src.resolve()==dst.resolve():raise ValueError('Refusing in-place modification')
    boot=src.read_bytes()
    if len(boot)!=c.BOOT_SIZE or sha(boot)!=SOURCE or boot[:8]!=b'ANDROID!' or struct.unpack_from('<I',boot,40)[0]!=4:raise ValueError('Unverified regs-b source')
    old=boot[c.KERNEL_OFFSET:c.KERNEL_OFFSET+c.KERNEL_SIZE]
    if sha(old)!=KERNEL:raise ValueError('Unverified XNU Mach-O')
    k=bytearray(old);o=lambda va:c.offset(k,va)
    if struct.unpack_from('<II',k,o(t.SCTLR))!=(0xd5181000,0xd5033fdf):raise ValueError('Native SCTLR/ISB altered')
    if struct.unpack_from('<II',k,o(0xfffffff0073f2368))!=(0xeb01001f,0x54000001):raise ValueError('Native guard altered')
    if struct.unpack_from('<I',k,o(t.ENTRY))[0]!=c.arm_b(t.ENTRY,t.CAVE):raise ValueError('Entry hook altered')
    if struct.unpack_from('<I',k,o(t.PRE))[0]!=c.arm_b(t.PRE,t.CAVE+16):raise ValueError('SCTLR hook altered')
    code=base64.b64decode(Path(__file__).with_name('dizi_mmu_walk_b_payload.b64').read_text().strip(),validate=True)
    if len(code)!=1569 or sha(code)!=PAYLOAD or t.CAVE+len(code)>=t.VECTOR_START or len(code)>t.LIMIT-t.CAVE:raise ValueError('Bad or overlapping ARM64 payload')
    if struct.unpack_from('<I',code,16)[0]!=0xf28b27a0:raise ValueError('Original MOVK not preserved')
    for i,target in ((12,t.FIRST),(32,t.SCTLR)):
        if struct.unpack_from('<I',code,i)[0]!=c.arm_b(t.CAVE+i,target):raise ValueError('Incorrect return branch')
    start,end=o(t.CAVE),o(t.LIMIT)
    if end-start!=1584:raise ValueError('Unexpected code-cave geometry')
    k[start:end]=b'\0'*(end-start)
    k[start:start+len(code)]=code
    changes=[i for i,(a,b) in enumerate(zip(old,k)) if a!=b]
    if not changes or any(i<start or i>=end for i in changes):raise ValueError('Patch escaped cave')
    out=bytearray(boot)
    for i in changes:out[c.KERNEL_OFFSET+i]=k[i]
    if sha(k)!=OUT_KERNEL or sha(out)!=OUTPUT:raise ValueError('Output SHA mismatch')
    dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(out)
    audit.parent.mkdir(parents=True,exist_ok=True)
    audit.write_text(json.dumps({'variant':'walk-b','source_boot_sha256':SOURCE,'output_boot_sha256':OUTPUT,'output_macho_sha256':OUT_KERNEL,'changed_macho_bytes':len(changes),'hardware_tested':False,'no_post_mmu_reads_or_writes':True,'note':'Status 0 guards failed; 1 L1 read; 2 L2 read; 3 both L3 read. No proof MMU enabled.','safety':'HIGH RISK. fastboot boot ONLY; NEVER flash.'},indent=2)+'\n')
    print('WALK-B:',OUTPUT,'changed bytes:',len(changes))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    a=p.parse_args();build(a.input,a.output,a.report)

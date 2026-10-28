#!/usr/bin/env python3
"""dizi XNU MMU boundary A/B probe: seven STACKLESS checkpoints.

The previous 6-stage build reached the confirmed _set_mmu_ttb return
but showed no new indicators. Unlike the previous six stubs which wrote
to [sp], this test installs seven register-only stubs on a SHA-pinned
COPY of the five-band Mach-O, beginning just AFTER the confirmed purple
marker. This isolates dependence on a writable bootstrap stack.

IMPORTANT: Like the already hardware-proven five-band probes, these
stackless stubs CLOBBER x9-x11 and NZCV. Those registers are not used by
the pinned instruction sequence in this narrow interval, but the probe
is NOT semantically neutral or a production fix. Never infer XNU MMU
enable solely from these pixels.

Unmodified original MSR TTBR1, MAIR, VBAR, SCTLR and ISB are verified.
No production EDK2, original Mach-O, other CPU or partitions touched.
"""
from __future__ import annotations
import argparse,hashlib,json,shutil,struct,subprocess,tempfile
from pathlib import Path

SOURCE_SHA="94947ff724ec85b005e7b6241e625867dadf5c10b053a1b2ae5f4f75e8b4a1d3"
ENTRY=0xfffffff0073f0488
CAVE=ENTRY+0x200
GOP=0xb8000000
STRIDE=6400
MARK="DIZI_XNU_MMU_STACKLESS_COMPARISON_V1"
STAGES=[
 ("POST_TTB_RETURN",0xfffffff0073f22b0,0x91400720,408,0xffff1493),
 ("BEFORE_TTBR1",0xfffffff0073f22b4,0x9240bc00,432,0xffff4500),
 ("AFTER_TTBR1",0xfffffff0073f22bc,0xaa1f03e0,456,0xffffd700),
 ("BEFORE_MAIR",0xfffffff0073f22fc,0xaa010000,480,0xff00ffc0),
 ("BEFORE_TLBI",0xfffffff0073f2308,0xd508871f,504,0xff80bfff),
 ("BEFORE_VBAR",0xfffffff0073f2330,0x91000000,528,0xffbfff00),
 ("AFTER_VBAR",0xfffffff0073f2340,0xf2e00000,552,0xffff00ff),
]

def branch(a,b):
 d=b-a
 if d%4 or not -(1<<27)<=d<(1<<27):raise ValueError("Unreachable ARM64 branch")
 return 0x14000000|((d>>2)&0x3ffffff)

def offset(buf,va):
 if len(buf)<4096 or struct.unpack_from("<I",buf)[0]!=0xfeedfacf:raise ValueError("Invalid Mach-O")
 n,cs=struct.unpack_from("<II",buf,16)
 if not 0<n<256 or cs>len(buf)-32:raise ValueError("Invalid Mach-O commands")
 p=32
 for _ in range(n):
  cmd,sz=struct.unpack_from("<II",buf,p)
  if sz<8 or p+sz>len(buf):raise ValueError("Bad command")
  if cmd==0x19:
   name,start,vs,fo,fs=struct.unpack_from("<16sQQQQ",buf,p+8)
   if name.rstrip(b'\0')==b'__TEXT_EXEC' and start<=va<start+min(vs,fs):
    return fo+va-start
  p+=sz
 raise ValueError("Unmapped executable VA "+hex(va))

def marker(word,y,color):
 clang=shutil.which("clang-18") or shutil.which("clang")
 obj=shutil.which("llvm-objcopy-18") or shutil.which("llvm-objcopy")
 if not clang or not obj:raise RuntimeError("LLVM tools missing")
 pa=GOP+y*STRIDE
 if not GOP<=pa and pa+9*STRIDE<=GOP+2560*STRIDE:raise ValueError("GOP bounds")
 asm=f"""
.section .text.probe,"ax",%progbits
.global stackless_marker
stackless_marker:
 movz x9, #{pa&0xffff}
 movk x9, #{(pa>>16)&0xffff}, lsl #16
 movz w10, #{color&0xffff}
 movk w10, #{(color>>16)&0xffff}, lsl #16
 movz w11, #7200
1:
 stp w10, w10, [x9], #8
 subs w11, w11, #1
 b.ne 1b
 dsb sy
 .inst {word:#x}
 nop
"""
 with tempfile.TemporaryDirectory() as temp:
  t=Path(temp)
  (t/"marker.S").write_text(asm)
  subprocess.run([clang,"--target=aarch64-none-elf","-c",str(t/"marker.S"),"-o",str(t/"marker.o")],check=True)
  subprocess.run([obj,"-O","binary","-j",".text.probe",str(t/"marker.o"),str(t/"marker.bin")],check=True)
  return bytearray((t/"marker.bin").read_bytes())

def main(inp,out,report):
 if inp.resolve()==out.resolve():raise ValueError("Refusing original Mach-O overwrite")
 data=bytearray(inp.read_bytes())
 h=hashlib.sha256(data).hexdigest()
 if h!=SOURCE_SHA:raise ValueError("Not pinned five-band source "+h)
 if struct.unpack_from("<II",data,offset(data,0xfffffff0073f2350))!=(0xd5181000,0xd5033fdf):
  raise ValueError("SCTLR/ISB changed")
 if struct.unpack_from("<I",data,offset(data,0xfffffff0073f22ac))[0]!=branch(0xfffffff0073f22ac,ENTRY+0x1d0):
  raise ValueError("Hardware proven PURPLE marker missing")
 ptr=CAVE; results=[]
 for name,site,original,y,color in STAGES:
  at=offset(data,site)
  if struct.unpack_from("<I",data,at)[0]!=original:
   raise ValueError("Wrong source opcode at "+name)
  b=marker(original,y,color)
  if len(b)!=44 or struct.unpack_from("<II",b,36)!=(original,0xd503201f):
   raise ValueError("Unexpected marker assembly layout")
  if not GOP<=GOP+y*STRIDE and GOP+(y+9)*STRIDE<=GOP+2560*STRIDE:
   raise ValueError("Invalid framebuffer coordinates")
  pos=offset(data,ptr)
  if any(data[pos:pos+len(b)]):raise ValueError("Occupied cave "+hex(ptr))
  struct.pack_into("<I",b,40,branch(ptr+40,site+4))
  struct.pack_into("<I",data,at,branch(site,ptr))
  data[pos:pos+44]=b
  results.append({"name":name,"hook":hex(site),"original":hex(original),"stub":hex(ptr),"y":[y,y+8],"argb":hex(color)})
  ptr+=44
 if ptr>ENTRY+0x600:raise ValueError("Cave limit exceeded")
 if struct.unpack_from("<II",data,offset(data,0xfffffff0073f2350))!=(0xd5181000,0xd5033fdf):
  raise AssertionError("MMU instruction changed")
 out.parent.mkdir(parents=True,exist_ok=True)
 out.write_bytes(data)
 meta={"marker":MARK,"source_sha256":h,"patched_sha256":hashlib.sha256(data).hexdigest(),
       "size":len(data),"stages":results,"no_stack_reads_or_writes_in_new_stubs":True,
       "scratch_regs_and_nzcv_clobbered":True,"sctlr_msr_isb_unchanged":True,
       "original_source_untouched":True,"on_device_verified":False,
       "comparison":"If first stackless band appears but prior stack-saving version did not, early stack access is suspect. Not proof by itself."}
 report.parent.mkdir(parents=True,exist_ok=True)
 report.write_text(json.dumps(meta,indent=2)+"\n")
 print(json.dumps(meta,indent=2))

if __name__=="__main__":
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument("--input",type=Path,required=True)
 ap.add_argument("--output",type=Path,required=True)
 ap.add_argument("--report",type=Path,required=True)
 a=ap.parse_args()
 main(a.input,a.output,a.report)

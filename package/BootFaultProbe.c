// SPDX-License-Identifier: MIT
// From UniXNU-fuxi package/BootFaultProbe.c (crash PC/LR/ESR/FAR + backtrace, SIGABRT reason scan). Its
// boot_progress_critical_exit is left out: ruan's (package/BootProgress.c) holds the thread instead.
// Observe real EL0 breakpoint state before exception delivery changes it.
// No allocation, process traversal, user-memory access or blocking in the trap.
#include <kern/task.h>
#include <kern/thread.h>
#include <arm/thread.h>
#include <kern/misc_protos.h>
#include <kdp/kdp_dyld.h>
#include <string.h>
#include <vm/vm_map.h>
extern int proc_selfpid(void);
extern void proc_selfname(char *, int);

struct boot_fault_record {
 unsigned valid;
 int pid;
 char name[32];
 uint64_t pc,lr,sp,fp,esr,far,slide,x[29];
};
static struct boot_fault_record faults[8];
static unsigned fault_lock,fault_count;

static void capture_exception(void *saved,unsigned esr,uint64_t far) {
 arm_saved_state_t *state=saved;
 if(__atomic_exchange_n(&fault_lock,1,__ATOMIC_ACQUIRE))return;
 struct boot_fault_record *f=&faults[fault_count++%8];
 f->valid=0;f->pid=proc_selfpid();proc_selfname(f->name,sizeof(f->name));
 f->pc=(uint64_t)get_saved_state_pc(state);f->lr=(uint64_t)get_saved_state_lr(state);
 f->sp=(uint64_t)get_saved_state_sp(state);f->fp=(uint64_t)get_saved_state_fp(state);f->esr=esr;f->far=far;
 f->slide=current_task()->task_shared_region_slide;
 for(unsigned i=0;i<29;++i)f->x[i]=(uint64_t)get_saved_state_reg(state,i);
 f->valid=1;
 __atomic_store_n(&fault_lock,0,__ATOMIC_RELEASE);
}

void boot_progress_user_breakpoint(void *saved,unsigned esr) {capture_exception(saved,esr,0);}
void boot_progress_user_abort(void *saved,unsigned esr,uint64_t far) {capture_exception(saved,esr,far);}
// No user memory access on the ordinary noncritical exit reporting path.
// A captured exception can have a handler; correlate only with a real exit.
void boot_progress_exit_fault(int pid,unsigned signal,char *out,unsigned long capacity) {
 struct boot_fault_record f={0};
 if(__atomic_exchange_n(&fault_lock,1,__ATOMIC_ACQUIRE))return;
 for(unsigned n=0;n<8 && n<fault_count;++n) {
  struct boot_fault_record *candidate=&faults[(fault_count-1-n)%8];
  if(candidate->valid && candidate->pid==pid){f=*candidate;break;}
 }
 __atomic_store_n(&fault_lock,0,__ATOMIC_RELEASE);
 // Signals without a recorded hardware exception (abort(), pthread_kill) take the registers the thread had when it entered the
 // kernel: the exiting thread is the one that died, as in a crash report on the console of other bring-ups.
 if(!f.valid && pid==proc_selfpid()) {
  arm_saved_state_t *state=find_user_regs(current_thread());
  if(state && is_saved_state64(state)) {
   f.valid=1;f.pid=pid;proc_selfname(f.name,sizeof(f.name));
   f.pc=(uint64_t)get_saved_state_pc(state);f.lr=(uint64_t)get_saved_state_lr(state);
   f.sp=(uint64_t)get_saved_state_sp(state);f.fp=(uint64_t)get_saved_state_fp(state);
   f.slide=current_task()->task_shared_region_slide;
  }
 }
 if(!f.valid)return;
 unsigned long n=snprintf(out,capacity,"p%d %.20s sig%u PC%llx LR%llx E%llx F%llx +%llx bt",
  f.pid,f.name,signal,f.pc,f.lr,f.esr,f.far,f.slide);
 if(pid==proc_selfpid()) {
  uint64_t frame=f.fp;
  for(unsigned depth=0;depth<12 && frame && !(frame&15) && n+16<capacity;++depth) {
   uint64_t pair[2];
   if(copyin(frame,pair,sizeof(pair)))break;
   n+=snprintf(out+n,capacity-n," %llx",pair[1]);
   if(pair[0]<=frame || pair[0]-frame>1048576)break;
   frame=pair[0];
  }
 }
}

// REASON-SCAN (kernel-only; excluded from the host formatting test)
// An aborting process that died of an uncaught exception holds the exception text in its malloc heap ("*** Terminating app due
// to uncaught exception 'X', reason: 'Y'"); the abort itself carries nothing. Scan the writable malloc regions of the exiting
// process (the calling thread owns the map) for the printable run that holds it, as the ios-sweet crash log does.
#define REASON_CHUNK 65536
static char reason_chunk[REASON_CHUNK+1];
static volatile int reason_busy;
void boot_progress_exit_reason(int pid,unsigned signal,char *out,unsigned long capacity) {
 if(!capacity)return;
 out[0]=0;
 if(signal!=6 || pid!=proc_selfpid() || __atomic_exchange_n(&reason_busy,1,__ATOMIC_ACQUIRE))return;
 vm_map_t map=current_map();
 vm_map_offset_t addr=0;uint64_t scanned=0;int best=0;
 while(scanned<(16ull<<20) && best<2) {   // 160 MiB of copyin faulted in untouched malloc pages on every SIGABRT
  vm_map_size_t size=0;natural_t depth=0;vm_region_submap_info_data_64_t info;
  mach_msg_type_number_t count=VM_REGION_SUBMAP_INFO_V2_COUNT_64;
  if(vm_map_region_recurse_64(map,&addr,&size,&depth,(vm_region_submap_info_64_t)&info,&count)!=KERN_SUCCESS)break;
  vm_map_offset_t base=addr;addr+=size;
  if(info.is_submap || (info.protection&(VM_PROT_READ|VM_PROT_WRITE))!=(VM_PROT_READ|VM_PROT_WRITE) ||
     info.user_tag<1 || info.user_tag>11 || !info.pages_resident)continue;
  for(vm_map_offset_t off=0;off<size && best<2;off+=REASON_CHUNK) {
   unsigned long len=(size-off)<REASON_CHUNK?(unsigned long)(size-off):REASON_CHUNK;
   if(copyin((user_addr_t)(base+off),reason_chunk,len))continue;
   scanned+=len;
   unsigned long start=0;
   for(unsigned long i=0;i<=len;++i) {
    int ok=i<len && (unsigned char)reason_chunk[i]>=0x20 && (unsigned char)reason_chunk[i]<0x7f;
    if(ok)continue;
    unsigned long run=i-start;
    if(run>=24) {
     // Rank 2: the full uncaught-exception line; rank 1: any run with a reason clause.
     char saved=reason_chunk[i];reason_chunk[i]=0;
     int rank=strnstr(reason_chunk+start,"uncaught exception",run)?2:strnstr(reason_chunk+start,"reason: ",run)?1:0;
     if(rank>best) {
      unsigned long m=run<capacity-1?run:capacity-1;
      memcpy(out,reason_chunk+start,m);out[m]=0;best=rank;
     }
     reason_chunk[i]=saved;
     if(best>=2)break;
    }
    start=i+1;
   }
  }
 }
 __atomic_store_n(&reason_busy,0,__ATOMIC_RELEASE);
}

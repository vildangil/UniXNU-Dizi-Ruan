> Latest owner clarification: all 9/A..G markers are explicitly confirmed, with a
> closer photo. G at 0xFFFFFFF0079B3B74 remains a **pre-VM-call** marker. See
> [VM continuation work](DIZI-VM-B.md). Earlier partial-G assessments are historical.

> Subsequent hardware update: a user photo matching INIT-B identifies new stages
> through F PROCESSOR, with G VM CALL partly obscured. The owner confirmed the exact image checksum. See [photo record](../data/dizi-init-b-hardware-photo-20261031.json).
> The local-only status below describes the earlier build session, before this photo.

# INIT-B — native arm_init continuation (2026-10-31)

Status: locally assembled and CPU-emulated; **not hardware tested**. GitHub
Actions dispatch is blocked by the environment proxy denying api.github.com.
The rolling release remains the photographed FLOW-B; do not confuse it with INIT-B.

## Exact input and output

Input FLOW-B: `3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c`.
Download the rolling asset only if that checksum still matches, otherwise rebuild
FLOW-B from the immutable fifth-NOSP release with the existing manual workflow.

INIT-B boot-v4 (68,800,512 bytes):
`f093fce1722245c097b6712169130cef63a2a40b7aaf9588aec1e11225af377b`.
Embedded Mach-O:
`dbe2c7cdcdf65214d1e3360a0c674f07a91fd41e96487939ab36f944c5eadecf`.
Payload and changed-byte count: [local build audit](../data/dizi-init-b-local-build-20261031.json).
Readable generated assembly: [source](../ci/dizi_mmu_init_b.generated.S), checked
byte-for-byte against the generator before assembling. Native source opcodes,
input SHA, recovered ARCH-B SHA and final output SHA are all checked.

## What the additional markers mean

All addresses below were disassembled from the exact FLOW-B Mach-O (SHA
`b740835898ca1be232e733c76af967a66fbe025c3b8e48f34c2febb8f889efc7`).
Original eight markers remain in the right column. New markers persist in the
left column, x=20, y=44..282; glyphs end at y309, within the 2-MiB alias.

| Marker | Hook VA | Evidence if visible | Displaced instruction |
| --- | --- | --- | --- |
| 9 CURRENT THREAD | 0xFFFFFFF0079B3AC8 | machine_set_current_thread returned | str wzr,[x20,#472] |
| A CPU BOOTSTRAP | 0xFFFFFFF0079B3AD0 | cpu_bootstrap returned | bl rtclock_early_init |
| B EARLY CLOCK | 0xFFFFFFF0079B3AD4 | rtclock_early_init returned | adrp x0,0xFFFFFFF007078000 |
| C STARTUP BOOT | 0xFFFFFFF0079B3AE4 | kernel_startup_bootstrap returned | bl timer_call_init |
| D TIMER CALL | 0xFFFFFFF0079B3AE8 | timer_call_init returned | bl cpu_init |
| E CPU INIT | 0xFFFFFFF0079B3AEC | cpu_init returned | bl processor_bootstrap |
| F PROCESSOR | 0xFFFFFFF0079B3AF0 | processor_bootstrap returned | adrp x0,0xFFFFFFF007078000 |
| G VM CALL | 0xFFFFFFF0079B3B74 | argument preparation before arm_vm_init reached | mov x0,x19 |

**G does not mean arm_vm_init returned.** The proposed post-VM site at
0xFFFFFFF0079B3B7C really is an ADRP after its call, but is deliberately not
instrumented: VM replacement may unmap the diagnostic framebuffer. An unconditional
post-VM renderer could introduce the very fault it purports to diagnose. A future
post-VM logger needs owned memory and validated mappings or a native console.

## Control flow and actual blockers

[Disassembly](../data/dizi-arm-init-after-thread-disassembly.txt) includes the
continuation, conditional paths, error exits and following cold routines. Addresses
must not be applied to another Mach-O. At 3ABC the old hook replays mov x20,x0;
3AC0 stores xzr/x19 into the returned thread, then 3AC4 calls
machine_set_current_thread at 0xFFFFFFF0073F2730. Invalid thread/cpu_data pointers
can fault before marker 9. Native cpu_bootstrap at 0xFFFFFFF0073E4D9C is simply RET
in this binary: marker A is not proof of processor initialization.

rtclock_early_init at 0xFFFFFFF0073F9BCC registers a timebase callback, checks
kern_feature_override and a boot argument. It does not prove timer IRQ delivery.
Its callback validates numerator/denominator and can panic on invalid timebase.
kernel_startup_bootstrap at 0xFFFFFFF00798A144 checks the startup table is nonempty
and a multiple of 24 bytes, sorts it and tail-calls
kernel_startup_initialize_upto(3). Empty/misaligned startup ranges explicitly panic;
startup callbacks can independently fault. Skipping these checks would be wrong.

After processor_bootstrap, 3B00 parses a memory-limit boot argument: success
loads w8 and sets x19=w8<<20; failure tries PE_get_default at 3B24 and otherwise
sets x19=0. All paths converge at 3B38. nanoseconds_to_absolutetime at 3B4C and
another boot-argument parse at 3B64 precede msr PAN,#1 at 3B68. G is after PAN and
before mov x0,x19 / arm_vm_init(x19, pointer 0xFFFFFFF00716ACF8) at 3B78.
A missing G after F includes these calls, stores and PAN; it does not isolate VM.

After VM: optional patch_low_glo (3B88 branch), PE_consistent_debug_inherit,
serial_init, kernel_startup_initialize_upto(4), debug/boot option branches,
PE_create_console, PE_init_printf(0), cpu_machine_idle_init(1), PE_init_platform(1,...).
The byte tested at 3CF0 must be set or the 3E38 path panics. Then ml_map_cpu_pio,
cpu_timebase_init, kptimer_curcpu_up, PE_init_cpu and fiq_context_init execute.
SecureDTLookupEntry / SecureDTGetProperty results at 3D28/3D48/3D68 must equal 1;
failures lead to explicit panic paths at 3E54, 3E7C, 3EA4. early_random and
machine_startup follow. A hypothetical return from machine_startup hits the stack
canary check (3DC4), restore sequence and RET at 3DE4; mismatch reaches
__stack_chk_fail at 3ECC. No such execution is hardware-confirmed here.

## Instrumentation validation and limits

The common tracer retains x0-x18, x30, NZCV and SP using 192 bytes of valid kernel
stack; x19-x29 and SIMD registers are untouched by the renderer. Each original
instruction is replayed after restoration. BL is relocated as ADRP/ADD x30 for
the **native** link address followed by B to the native target; ADRP is recomputed
for its original target page. Copying either original opcode to the cave would
corrupt control flow or data addressing. No native calls are skipped.

64 Unicorn comparisons (16 hooks x four NZCV patterns) match all GPRs, SP, NZCV,
native data stores and continuation PC against executing the original instruction.
They execute the real renderer and require framebuffer writes bounded to the
first 2MiB. BL comparisons stop before native callee execution. This does not
validate cache coherence, MMU/Device attributes, hardware stack bounds, asynchronous
exceptions or future remapping. VBAR/vectors and existing firmware are unchanged;
no extra PSCI calls, GIC writes, page-table writes or exception handler are added.

## Full boot and SMP remain separate work

Offline audits reproduce 6,061 MiB recovery RAM vs 7,944 MiB legacy FDT and the
high-bank reservation conflict. No allocator is approved by those numbers.
The eight unique Aff1 IDs and common reset mask pass source checks; read-only
PSCI helper compiles for AArch64. Neither PSCI queries nor CPU_ON ran on hardware.
Keep cpus=1 and board.example=true. Source XNU workflow needs its pinned macOS/Xcode
runner and upstream/submodules; prelink needs the official Apple IPSW and a
compatible source-built kernel. Host prelink is not loadability qualification.
ADT identity, live handoff GetMemoryMap ownership, VM reservations, native GIC/timer
IRQ delivery, panic path, root storage and userland remain unresolved. No justified
native subsystem fix was found that can be validated without these inputs.

## Reproduce and request one hardware test

Activate the LLVM tools described in the saved environment start instructions.
From the device checkout:

```sh
python3 ci/patch_dizi_mmu_init_b.py --input /tmp/flow-b.img --output /tmp/init-b.img --report /tmp/init-audit.json
python3 ci/check_dizi_init_b_emulation.py --input /tmp/init-b.img --output /tmp/init-emulation.json
```

The existing manual xnu-mmu-ab-lab.yml has the new init-b choice, retaining slot-b
as default and all rollback variants. Its init-b path builds all predecessors,
checks FLOW-B assembly, builds INIT-B, runs emulator checks and retains JSON audits.
No automatic image trigger was added. When API access is restored, dispatch that
workflow on main with variant=init-b, inspect success and checksum before publishing.
No successful remote run or new release is claimed for this session.

Only after obtaining the checksum-matching INIT-B image, the single next device
test is `fastboot boot Mu-dizi-XNU-INIT-B-HIGH-RISK.img`. Photograph both columns,
including the last visible line. Never flash this experiment. A marker establishes
only its code path; it is not proof of IRQs, scheduler, VM completion or userland.

Full existing workflow build step was subsequently executed locally from immutable fifth-NOSP through every predecessor to INIT-B, including FLOW-B source reproduction, emulator checks and final SHA256SUMS verification. It passed; corrupted FLOW-B input was rejected before producing output. This remains local execution, not a GitHub Actions run.

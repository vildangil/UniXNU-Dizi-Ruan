# Dizi XNU: 8-point `flow-b` trace within `_arm_init`

## Hardware result: all eight flow-b stages on real dizi (2026-10-31)

The latest owner-provided physical tablet photograph shows **every**
`flow-b` stage (`1 PROLOGUE` through **`8 THREAD READY`**),
in addition to `ARCH REGS OK`. Boot image SHA-256 was
`3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c`.
Actions run:
https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41194255999 .

The last native address reached is **`0xFFFFFFF0079B3ABC`**,
after the call to `_thread_bootstrap` returned, but before
the displaced `mov x20,x0` is executed. This confirms code-path
progress to that boundary, **not** the scheduler, interrupt delivery,
full `_arm_init` or multi-CPU boot.

Preserved physical result:
[`data/dizi-flow-b-eight-markers-hardware-20261031.json`](../data/dizi-flow-b-eight-markers-hardware-20261031.json).
The next Work session should read
[`docs/AI-WORK-HANDOFF.md`](AI-WORK-HANDOFF.md) and
instrument the validated **following** native call boundaries
in one high-value diagnostic before claiming further progress.

## Hardware baseline (31 October 2026)

The physical Redmi Pad Pro dizi photograph of the **`arch-b`** image
shows, in order, `XNU ENTRY`, `PRE ALIAS ARMED`,
`POST SCTLR OK`, `GUARD PASSED`, `TPIDR DONE`, and
**`ARCH REGS OK`**. The associated release (Actions
[run 41192216023](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41192216023))
had boot SHA-256
`58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`.
This proves that the first instrumented `_arm_init` instruction was
reached on CPU0 and the six EL1/MPIDR/timer/MMU/TPIDR/MIDR
checks passed. It **does not** prove that `_arm_init` finished or
that any other core was started.

The photo is recorded in
[`data/dizi-arch-b-registers-hardware-20261031.json`](../data/dizi-arch-b-registers-hardware-20261031.json).

## New `flow-b`: trace deeper without guessing where the CPU stopped

The existing **single manually dispatched workflow**
[`xnu-mmu-ab-lab.yml`](../.github/workflows/xnu-mmu-ab-lab.yml)
now offers an **opt-in `flow-b`**. It starts from the exact
SHA-pinned **hardware-tested `arch-b`** boot image and keeps all
previous bootloader, native XNU MMU transition, guarded high-virtual
framebuffer alias and architectural register checks unchanged.

Eight native one-instruction sites **inside `_arm_init`** branch into
a small instrumentation routine, then replay their original
instructions and resume at the next native instruction.

| Marker | Native hook VA | Meaning if reached |
| --- | --- | --- |
| `1 PROLOGUE` | `0xFFFFFFF0079B3424` | The `_arm_init` stack frame and callee-saved register prologue completed |
| `2 TBI RETURN` | `0xFFFFFFF0079B3448` | The call to `_arm_set_kernel_tbi` returned |
| `3 KC REBASE` | `0xFFFFFFF0079B3984` | Control reached the common kernel-collection post-adjustment path |
| `4 CPU DATA` | `0xFFFFFFF0079B39A4` | Boot arguments were copied; `_cpu_data_init` is about to be called |
| `5 PE PLATFORM` | `0xFFFFFFF0079B39B0` | `_cpu_data_init` returned; platform initialization is about to be called |
| `6 TIMER WFE` | `0xFFFFFFF0079B39C8` | The architecture timer and WFE configuration helpers returned |
| `7 CPU TOPO` | `0xFFFFFFF0079B3A78` | CPU topology and boot CPU-number routines returned and earlier range checks were passed |
| `8 THREAD READY` | `0xFFFFFFF0079B3ABC` | The call to `_thread_bootstrap` returned |

The progress labels are **control-flow markers, not subsystem tests**:
e.g. `TIMER WFE` does not prove any timer interrupt fired;
`CPU TOPO` does not prove secondary CPU bring-up; and
`THREAD READY` does not prove kernel scheduling or userland.

Unlike the older `bootpath-b` test (which shares one status row), these
eight markers appear in their **own rows to the right of the existing
arch-b text**. If a later routine crashes, earlier markers should remain
visible. All writes stay inside the existing first 2-MiB TTBR1
Device framebuffer alias.

## Register integrity and verified modification boundary

The `flow-b` tracer uses an additional code cave
`0xFFFFFFF0073F1800` through `0xFFFFFFF0073F1FF0`.
It is an all-zero, PINNED 2,032-byte interval **after** the
`_LowExceptionVectorBase` 2-KiB vector table and **before**
`_resume_idle_cpu` at `0xFFFFFFF0073F2000`. The new trace
fits in 1,163 bytes. The cave and previously confirmed
`start_first_cpu` / VBAR addresses are within the
same 2-MiB executable translation block measured by `walk-b`.
It does **not** replace any of the exception vector entries.

Each trampoline is entered after the native `_arm_init` stack
prologue; it uses a 16-byte aligned, temporary stack frame
to preserve `x0–x18`, `x30`, and `NZCV`. It never modifies
`x19–x29`; `SP` is restored. It draws a stage, restores
the original register/flags state, **replays the displaced
native opcode** and branches back to the exact next instruction.
No new PSCI calls, `CPU_ON`, GIC MMIO or page-table writes
are introduced, although the earlier tested `arch-b` alias
setup **still installs one guarded L2 framebuffer descriptor**.

Fail-closed build rules verify the input Android boot-v4 and Mach-O
SHA-256, that the entire second cave was initially zero,
the eight exact native instructions, the ARM64 blob SHA,
the restored instructions and branch destinations, and that no
other Mach-O/boot bytes changed. CI also recompiles the
[readable assembly source](../ci/dizi_mmu_flow_b.S.in)
with the original pinned 5×7 font and compares every byte with the
[versioned ARM64 payload](../ci/dizi_mmu_flow_b_payload.b64)
using [`ci/check_dizi_flow_b_source.py`](../ci/check_dizi_flow_b_source.py).

- Input hardware-tested `arch-b` boot SHA:
  `58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`
- Output `flow-b` boot SHA:
  **`3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c`**
- Output embedded Mach-O SHA:
  `b740835898ca1be232e733c76af967a66fbe025c3b8e48f34c2febb8f889efc7`
- Compiled flow tracer SHA:
  `dbdb592ce93c7ad750874c32423b14d4ffa7499ef54a82b3e880cd7bd73f2c6f`
- Exactly **940 changed Mach-O bytes**, confined to the
  1,163-byte code insert and 8 one-instruction branch sites.
- The image and source were independently built and checked
  locally; **the user has since tested it successfully on physical dizi
  through all eight markers** (see the hardware result above).

### Operational limits

The eight extra instruction hooks make this experimental image **more invasive**
than a pure register read. A wrong assumption about stack
availability, executable padding or the framebuffer mapping could
cause a CPU fault or hang. The 2-MiB framebuffer alias might also
be changed later during VM initialization, making a missing status
inconclusive.

The previous `arch-b` and `bootpath-b` are retained for
comparison; `slot-b` is the safe manual-workflow default.
Do **not** run `cpus=2` or a real secondary CPU test until
we have reliable platform/PSCI/ADT topology and XNU bootstrap evidence.

Only load the image temporarily via **`fastboot boot`**, never
`fastboot flash`. Have an Android recovery path and the known
arch-b image available for rollback. The requested photo has now confirmed all 8 stages. Inspect the following
native XNU call path and design a single follow-up test; do not guess
that the first missing call is a fault without checking control flow.

# Dizi XNU: deep single-run bootstrap diagnostics and SM7435 SMP preflight

## Current hardware checkpoint — October 31, 2026

The physical dizi screenshot of the corrected `alias-b` image
(from [Actions #41136028600](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41136028600),
SHA-256 `ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`)
shows:

```text
DIZI XNU ENTRY
PRE ALIAS ARMED
POST SCTLR OK
GUARD PASSED
```

**Hardware-confirmed:** native `SCTLR_EL1`+ `ISB` completed,
the code resumed after the MMU transition, the high virtual
framebuffer alias `0xFFFFFFF004000000` was writable, and
the native `cmp x0,x1; b.ne .` check was passed.

**Not yet confirmed:** `CPACR_EL1`, `TPIDR_EL1`,
return from the early assembly bootstrap, `_arm_init`, actual
secondary CPU startup, scheduler, rootfs, IOKit or iPadOS.

## On-device deep-b result — _arm_init CPU0 confirmed (31 October 2026)

The user tested `deep-b` on physical dizi. After rotating the
photograph to read the console, the visible messages are:

```text
DIZI XNU ENTRY
PRE ALIAS ARMED
POST SCTLR OK
GUARD PASSED
TPIDR DONE
ARM_INIT CPU0
```

The `RETURN TO ARM_INIT` line is overwritten by the final
`ARM_INIT CPU0` message because the tracer deliberately reuses
the same y296 display row. Native handoff to the first
instrumented `_arm_init` opcode at `0xFFFFFFF0079B3404`
is therefore **confirmed**; successful completion of
`_arm_init`, interrupts, memory allocation, and any other
CPU remains **unconfirmed**.

The confirmed image's SHA-256 is
`4acf22fe3b0fb389ccc057b591b7c41fc57e0e0c32eaa246342f34e85c232c45`.
[Structured hardware evidence](../data/dizi-deep-b-arm-init-hardware-20261031.json)
is recorded separately; no new branch was created.

## Additional on-device read-only architecture diagnostics: arch-b

`arch-b` is a new **opt-in** variant in the same manual
MMU A/B workflow, based on the **exact** hardware-confirmed
`deep-b` boot-v4 binary. It changes **only** the existing
1,584-byte diagnostic code cave; none of the 8 native
XNU hook opcodes, `SCTLR`, `ISB`, `CMP/B.NE`,
DarwinBoot or EDK2 are changed.

The `_arm_init` entry handler now checks six read-only conditions:

| Check | Expected value | Why it matters |
| --- | --- | --- |
| `MPIDR_EL1` Aff0–Aff2 | Zero | Confirms this remains the bootstrap CPU |
| `CurrentEL` | `0x4` (EL1) | Checks the exception level after MMU-on |
| `CNTFRQ_EL0` | 19,200,000 Hz | Checks architectural timer frequency against recovery |
| `SCTLR_EL1.M` | 1 | Confirms stage-1 MMU remains enabled |
| `TPIDR_EL1` | 0 | Verifies the earlier native TPIDR zeroing |
| `MIDR_EL1` | Nonzero | Checks processor ID register can be read |

If all conditions hold, the final status line displays
**`ARCH REGS OK`**. If any comparison fails, it shows
**`ARCH REGS FAIL`**; this variant does *not* identify
which of the six disagreed, so use a targeted follow-up probe
rather than overriding the guard. A trap before printing may
leave an older message visible. None of these read-only
register checks issue a PSCI call or read GIC MMIO.

To be precise: **`arch-b` still retains the existing
`deep-b` framebuffer-alias setup**, which writes one
guarded TTBR1 L2 descriptor before enabling the MMU.
The architecture diagnostics themselves make no additional
page-table writes. It is not an entirely passive boot.

- Expected full boot-v4 SHA-256:
  `58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`
- Embedded Mach-O SHA-256:
  `af2e080430be9a41bf608d51551086720704a4fca18a3a796948c6778c05c6c9`
- AArch64 diagnostic region size: **1,581 / 1,584 bytes**.
- Only 1,212 bytes of Mach-O differ from `deep-b`;
  all changes are within that existing diagnostic cave.
- Reproduced twice locally, with byte-identical full images.
- **Not hardware-tested** until the next physical `fastboot boot`.

The old `deep-b`, `alias-b`, `slot-b` and other manual
variants remain available, with the safer `slot-b` default.

## Additional platform memory and framebuffer evidence (offline)

[`ci/check_dizi_memory_map.py`](../ci/check_dizi_memory_map.py)
cross-checks redacted Linux recovery DT observations,
the older reference FDT, and physically observed
`walk-b`/`fbwalk-b`/`slot-b`/`deep-b` results.

The recovery DT describes **6,061 MiB** of physical RAM
versus **7,944 MiB** in the old reference FDT — a discrepancy
of **1,883 MiB**. The high-memory 1-GiB reference candidate
intersects recovery-observed reservations beginning at
`0x8F6B00000`; it is **not** approved as a UEFI or XNU
runtime allocation. The physical splash reservation is
`0xB8000000` through `0xBAAFFFFF` (43 MiB),
and the guarded 2-MiB framebuffer alias remains within it.

These checks are offline only. They do not establish
a live UEFI `GetMemoryMap`, Apple ADT allocation ownership,
working storage, actual GIC register values or a usable
XNU panic handler. A manually launched `validate.yml`
now uploads a separate memory-evidence JSON artifact
in addition to the CPU topology audit.

## New `deep-b`: one-run XNU CPU bootstrap checkpoint collection

The existing **single manual MMU workflow in main** now offers
`deep-b` as an opt-in variant. It starts from the exact pinned,
hardware-tested `slot-b` source and includes the corrected
`alias-b` guards and high-VA framebuffer alias.

The new stage tracer inserts a single displaced-instruction-safe
branch at each of these XNU instruction addresses, without altering
the original `SCTLR/ISB`, native `cmp/b.ne`, or EDK2:

| Native site VA | Instruction | New visible checkpoint |
| --- | --- | --- |
| `0xFFFFFFF0073F0488` | Original entry tracer | `DIZI XNU ENTRY` |
| `0xFFFFFFF0073F234C` | `movk x0,#0x593d` | `PRE ALIAS ARMED` or `ALIAS GUARD FAIL` |
| `0xFFFFFFF0073F2358` | `movk x1,#0,lsl#48` | `POST SCTLR OK` |
| `0xFFFFFFF0073F2370` | `mov x0,#0x300000` | `GUARD PASSED` |
| `0xFFFFFFF0073F2378` | `msr TPIDR_EL1,xzr` | `TPIDR DONE` |
| `0xFFFFFFF0073F2388` | `ret` | `RETURN TO ARM_INIT` |
| `0xFFFFFFF0073F239C` | `br x0` | `SECONDARY BRANCH` (alternate path) |
| `0xFFFFFFF0079B3404` | `sub sp,sp,#0xd0` at `_arm_init` | `ARM_INIT CPU0` or `ARM_INIT OTHER CPU` |

The final return/secondary-branch/arm-init checkpoint reuses
the same panel row below y296 to keep the entire renderer
within the **first 2 MiB** of the framebuffer alias. The
`ARM_INIT` checkpoint additionally samples `MPIDR_EL1`,
masks Aff0:Aff2, and distinguishes CPU0 affinity zero from
another core. **It does not wake or test another CPU.**

Reproducible SHA-pinned image:

- Source slot-b boot-v4 SHA-256:
  `ab1edbbc8b05fe9b59f0f6909ce84c75faf40c1c98edea6acb50d268c9e688ee`
- New `deep-b` boot-v4 SHA-256:
  `4acf22fe3b0fb389ccc057b591b7c41fc57e0e0c32eaa246342f34e85c232c45`
- Embedded Mach-O SHA-256:
  `0248d8724fa4978dd2391088d82e06c9ed1130829d1d77f20229eb512a1abecd`
- Tracer: **1,543 of 1,584** SHA-verified code cave bytes.
  Eight original one-instruction hook sites and only this code cave
  may differ from the `slot-b` source.
- The ARM64 assembler produces no relocations; two local rebuilds
  produced exactly the same `boot.img`. Native MMU instructions
  and existing kernel page table checks are unchanged.
- **Not yet tested on physical dizi.** Do not assume progression
  beyond `GUARD PASSED` before the next device photograph.

Source: [ASM](../ci/dizi_mmu_deep_b.S.in) and
[SHA-pinned image patcher](../ci/patch_dizi_mmu_deep_b.py).

## SM7435 common: real eight-core topology versus actual SMP

The pinned
[`UniXNU-sm7435-common`](https://github.com/vildangil/UniXNU-sm7435-common)
SoC source describes these eight **physical affinity IDs**:

| Logical DT node | Physical MPIDR Aff0:Aff1 | DT group |
| --- | --- | --- |
| cpu0 | `0x000` | E |
| cpu1 | `0x100` | E |
| cpu2 | `0x200` | E |
| cpu3 | `0x300` | E |
| cpu4 | `0x400` | P |
| cpu5 | `0x500` | P |
| cpu6 | `0x600` | P |
| cpu7 | `0x700` | P |

The original SoC SMP source patch selected `MPIDR & 0xFFFF`
only when `HAS_CLUSTER || defined(BCM2837)`. If both were
false, it selected `MPIDR & 0xFF`, collapsing all eight
Parrot physical IDs to zero. The SM7435-only patch is now
**unconditional**:
`and x0, x15, #0xFFFF` before the reset handler compares
`x0` with the recorded `CPU_PHYS_ID`. `0x100` remains
a *physical affinity ID*, not logical CPU index 1.

This change is pinned in main `feeds.toml` at commit
`22a71774c8ebf8ca6f2816bf774ff05d6b96e828`.
The patch passed an independent `git apply --check` source
fixture and all eight IDs were checked for uniqueness.
It has **not** been built and hardware-verified for secondary
CPU XNU entry. The older inherited `sheng-smp` boot-option
assumptions, CPU_DATA physical-ID provisioning, Apple ADT topology,
GICR/timer setup and cluster scheduler still need review.

The source preflight [`ci/check_sm7435_smp.py`](../ci/check_sm7435_smp.py)
audits the eight CPU nodes, PSCI SMC, GICD `0x17200000`,
GICR `0x17260000` / stride `0x20000`, and the
19.2 MHz architectural timer. It verifies safe `cpus=1`
defaults and two **opt-in** `cpus=2` menu profiles.
The CPU count and register addresses are DT descriptions
and do **not** prove the actual runtime register readbacks.

### Source-only PSCI query helper now available

[`package/Sm7435PsciReadOnly.c`](../package/Sm7435PsciReadOnly.c)
and [its header](../package/Sm7435PsciReadOnly.h) implement
**read-only** PSCI queries following the AArch64 SMCCC calling
convention: `PSCI_VERSION` (`0x84000000`),
`PSCI_FEATURES(CPU_ON64)` and
`AFFINITY_INFO64` for physical affinities
`0x000..0x700`. The function returns all results in a
caller-provided 8-CPU snapshot without power-control calls.

This helper was compiled locally using
`clang --target=aarch64-none-elf -ffreestanding -Wall -Wextra -Werror`.
The object disassembly contains `MRS MPIDR_EL1`
and the read-only `SMC #0` wrapper. It is now included
in `validate.yml` as a **compile-only** check. The helper
is not linked into EDK2 or XNU and is **not run on the device**.
When incorporated later, it must run only in a verified EL1
calling context, with a working stack, accessible output RAM,
and a confirmed SMC conduit. It can return an unsupported or
disabled PSCI result; an SMC may trap if called in an
inappropriate EL/context. It does **not** confirm that the
secondary CPU reset vector, GICR, IPI or timers work.

### Real secondary CPU verification gates

Do not attempt `PSCI CPU_ON` directly from the early
`start_first_cpu` diagnostic cave. The correct CPU1 physical
trampoline, executable memory ownership and secondary
`CPU_DATA` state are not yet established. Start with
hardware read-only `PSCI_VERSION`, `PSCI_FEATURES(CPU_ON)`,
`AFFINITY_INFO`, MPIDR and GICR_TYPER readbacks, using a
validated call boundary that preserves all live XNU registers.
Then verify the exact Apple ADT CPU numbering and ArmCpu
secondary reset handler. Only **after** `deep-b` confirms
`_arm_init` and those checks pass should `cpus=2` be
considered as the first active SMP test, followed by
IPI/timer delivery and eventually 8-CPU work.

PSCI `AFFINITY_INFO` can report ON/OFF/ON_PENDING, but does
not itself launch any secondary processor. The function IDs
are the public ARM PSCI ABI; no Qualcomm power MMIO or
SM8550/sheng drivers may be substituted.

**Testing:** retain Android recovery, backups and the
hardware-confirmed `alias-b` release for rollback. Use
temporary `fastboot boot` only, **never `fastboot flash`**.

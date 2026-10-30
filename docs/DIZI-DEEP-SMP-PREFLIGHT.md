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

## 2026-10-31 — prepare FB8 runtime readback after hardware FBFAIL8

- Real Redmi Pad Pro FB-BRIDGE-B reports `FBFAIL8`, leaving ambiguity between occupied new framebuffer L2[0x20] and changed code L2[0x39].
- Added separate pinned, read-only `fb8-readback-b`: display both 64-bit runtime values, distinct statuses, deliberate pre-switch WFE; **no descriptor store or native TTBR switch**.
- Wired existing manual MMU workflow plus owner-only `/run-dizi-fb8-readback` control-PR comment. No push/PR trigger; no automatic rolling release replacement. Published release is unchanged.
- Local reproducible candidate SHA-256: `a0ca687c085a56460ac4307e304d6025f909ac250e4b4b9201173fde902a8335`. GitHub Actions #41215735588 **passed**, with FB8 source, negative cases, SHA and image tests; artifact ID 13047639826. Release publishing was skipped, and existing rolling SHA 4ff3a8f6... remains unchanged. Physical device test is still pending.

## 2026-10-31 — guarded native TTBR1 framebuffer bridge, CI preflight

- Physical TABLE-B/LEAF-B/STACK-B showed a **missing** new-root
  L2[0x20] high-VA Device framebuffer mapping, valid code leaves,
  and future EL1-writable stack/data pages backed by the expected
  bootstrap physical pages. Effective post-switch access is unknown.
- Existing `fb-bridge-b` code in `main` uses exact register and
  table guards, transfers **one** 2-MiB Device-nGnRnE L2 block
  descriptor, and prints pre-/post-native-switch text. The original
  privileged TTBR/TLBI/DSB/ISB instructions are not altered.
- Added `ci/check_dizi_fb_bridge_contract.py` to the same manual
  `fb-bridge-b` workflow and existing device-profile `validate.yml`.
  It audits photographed topology, permissions, source guard order,
  the unique L2 write and DSB, plus four deliberate failure cases.
- Independent inspection of current GitHub source/evidence passed.
  The new Python preflight has **not yet completed GitHub Actions**
  and the `fb-bridge-b` image has **not been physically tested**.
  The previously published release still contains `stack-b`.
- Bridge expected boot SHA256:
  `4ff3a8f6839bc3ba9f33a91356b9f55e4e8cd65d6fafaf30391ba41e5babd195`.
  [Bridge notes](docs/DIZI-FB-BRIDGE-B.md).
- The next single owner-authorized physical test is `fb-bridge-b`
  after successful manual Actions and exact image hash verification.
  Do **not** claim a functioning framebuffer driver, VM return,
  interrupts, SMP, rootfs or userland from this preflight.

## 2026-10-31 — FB-BRIDGE-B guarded framebuffer alias repair prepared (NOT hardware-tested)

- Confirmed from prior hardware data that prospective TTBR1 L2[0x20] was zero
  while the previous high-VA framebuffer alias was present only in the old root.
- Added `ci/dizi_mmu_fb_bridge_b.S.in` and SHA-pinned patcher.
  Before native TTBR switch, nine guards validate TCR/MAIR, old/new roots,
  both L2 descriptors and exact native `phystokv` results.
  Only if all pass, the experiment installs a single 2-MiB Device
  framebuffer L2 descriptor and verifies readback; otherwise displays
  `FBFAIL1`..`FBFAIL9` and intentionally stops before switching.
- Adds post-`TLBI VMALLE1IS; DSB ISH; ISB` hook at
  `0xFFFFFFF0073EA130`: `FB NEW TTBR OK` would demonstrate
  continued high-VA framebuffer output under the new root.
- Rebuilt image twice locally byte-identically, verified only native
  MMU/barrier instructions remain unchanged, mutation allowlist and
  corrupt-input rejection. Full boot SHA-256:
  `4ff3a8f6839bc3ba9f33a91356b9f55e4e8cd65d6fafaf30391ba41e5babd195`.
- Added explicit `fb-bridge-b` option to the EXISTING manual workflow in
  `main`; `slot-b` default, `stack-b` rollback, `cpus=1` untouched.
- **Local build/test passed. CI dispatch/publication and device
  hardware result still pending.**
  [Detailed guard/status documentation](docs/DIZI-FB-BRIDGE-B.md).

## 2026-10-31 — STACK-B hardware stack/data result

- Recorded B=FFFFFFF007BB3DD0, P/Q=00600008039B3603, D=0060000802F6A603,
  M=0060000802F6C603, L=3333, R=804191000, S=0.
- Four actual L3 readbacks show private EL1 RW/NX and match bootstrap physical
  reference; SP matches native arm_init + arm_vm_init frames inside intstack.
- Kept old-table/content comparison and effective switch/access unverified.
- Documented prerequisites for a guarded alias repair and post-TLBI checkpoint;
  no new mapping write or image in this analysis step.

## 2026-10-31 — STACK-B successfully published

- [Actions #41205403802](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41205403802) passed on main implementation 7b1e86ca.
- Downloaded image SHA 0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed verified; GitHub asset digest agrees.
- CI JSON/emulation artifact id 13043368686 recorded; STACK-B hardware test pending.
- Decoder distinguishes descriptor permission evidence from effective access and
  preservation of current stack backing; no such hardware claim was made.

## 2026-10-31 — STACK-B active-stack/data mapping probe

- Captures actual SP, future translations for both frame endpoint pages and two
  kernel-global pages, selecting prospective TTBR0/TTBR1 by canonical VA.
- Reports terminal level and inherited EL1 read-only restrictions per target;
  distinguishes invalid readbacks from refused/placeholder values.
- 240 actual-code comparisons pass against a separate host walker; no table writes.
- Added stack-b to existing manual workflow; remote CI/hardware result pending.

## 2026-10-31 — LEAF-B hardware PTE result

- Recorded complete N/F/K/C/H/X/V/S photo; S=0 and F=0 confirmed again.
- Decoded four valid L3 pages: expected physical code pages, AF1/AP2/PXN0/UXN1.
- Added reproducible leaf decoder with PXN, invalid-page and skipped-read checks.
- Kept effective translation and future stack/data proof separate; documented
  stale-TLB risk for any checkpoint before native TLBI. No new image in this step.

## 2026-10-31 — LEAF-B successfully published

- [Actions #41203388717](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41203388717) passed on main source 685c6b7b.
- Downloaded published image SHA 0b5e0f0cebfc10d5e39b8a8f4db316740ad455efd2e154604ff3a2e4ee2e932f matches pin and GitHub digest.
- CI JSON/emulation artifact id 13043741003 recorded; no LEAF-B hardware result.
- Next test collects N/F/K/C/H/X/V/S before changing any new mapping.

## 2026-10-31 — TABLE-B hardware descriptors and LEAF-B

- Recorded full TABLE-B photo: actual absent framebuffer L2 entry with S=0;
  kernel L2 points to L3 at 0x804193000.
- Added host descriptor decoder that distinguishes skipped zeros and table/leaf types.
- Prepared read-only LEAF-B capture of VM/helper/tracer/vector L3 PTEs before
  physmap metadata replacement, without installing an alias or post-switch writer.
- 240 emulator comparisons pass; remote LEAF-B CI/hardware pending.

## 2026-10-31 — TABLE-B published and release verified

- [Actions #41202475579](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41202475579) succeeded; source commit 08f12cc3 is in main.
- Downloaded release and GitHub asset digest match SHA 5479a94e36a2e3527131c9401ff98e1024bf3fc6f4356952a5e901cf720eb4e3.
- JSON/emulation artifact id 13042913736 recorded; no TABLE-B device result yet.
- Final probe is before physmap metadata replacement; no new mapping writes.

## 2026-10-31 — TABLE-B descriptor probe

- Added bounded read-only native-root/L1/L2 capture with explicit refusal statuses.
- Uses exact native phystokv only for a page inside native allocation and RAM bounds.
- Preserves historic SWITCH-B output SHA; four VM hooks replace eight old FLOW hooks.
- 160 emulation cases pass with exact displayed descriptors/status and no table writes.
- Extended existing manual workflow only; TABLE-B remote CI/hardware status pending.

## 2026-10-31 — SWITCH-B hardware numeric snapshot

- Recorded photographed N=0x804191000, O=0x802F6E000, T=0x22A51A251A and G.
- Added host TCR/root decoder: 38-bit VA, 4KiB granule, 8-bit initial L1 index;
  calculated framebuffer and kernel indices without claiming descriptor readbacks.
- Traced native virtual-root pointer provenance for the next bounded table probe.
- No new image or post-switch/VM-completion claim.

## 2026-10-31 — SWITCH-B successfully published

- Owner lifted the accidental pause; implementation a2b00cff is in main.
- GitHub Actions run 41200797504 succeeded and published the existing single-image release.
- Downloaded release SHA-256 verified: b4e33fd8fc6064546e31083f589a691184c0e5fc52766ba32c05723597b31bc4.
- CI JSON/emulation artifact id 13042621469 exists; redirected artifact/log downloads
  are blocked locally. No SWITCH-B hardware test is claimed.

## Earlier local preparation — 2026-10-31

- Recorded VM-B device photo through G (pre-switch), with E not identified.
- Prepared SWITCH-B numeric pre-switch root/TCR snapshot; no new table edits or
  unsafe post-switch framebuffer stores. Existing VM-B remains byte-identical.
- 64 SWITCH-B and 64 VM-B emulator cases pass. Existing workflow updated locally
  only; publication remains stopped by owner instruction.

## 2026-10-31 — VM-B and confirmed INIT-B G

- Owner confirms 9 and every A..G on the closer INIT-B photo; G precedes arm_vm_init.
- Disassembled native VM path and confirmed TTBR1 switches before TTBR0.
- Added vm-b in the existing manual workflow: eight VM-internal stages before the
  switch, plus bounded clearing of stale diagnostic text; INIT-B remains unchanged.
- Added pinned 18-segment Mach-O bounds/overlap and framebuffer-alias audit.
- Local full predecessor build and 64 VM-B + 64 INIT-B emulator comparisons pass.
- No VM-B hardware test, remote Actions run or release publication; API CONNECT 403 persists.

## 2026-10-31 — INIT-B device photo received

- Recorded the supplied two-column photo: stages 1..8 and new 9..F identifiable;
  final G partially obscured, exact image SHA explicitly confirmed by the owner.
- Identified a tracer readability defect: foreground-only rendering overlaps
  stale legacy diagnostics in the left column. Preserved the tested image.
- Separated processor_bootstrap return evidence from unproven arm_vm_init execution,
  VM completion, IRQ delivery, SMP and userland.

## 2026-10-31 — INIT-B continuation (local verification only)

- Added init-b to existing manual MMU workflow; preserved defaults and rollback variants.
- Relocated BL/ADRP correctly, preserved native link addresses, and added eight persistent left-column checkpoints.
- Kept final checkpoint before VM replacement to avoid faulting through an invalidated framebuffer alias.
- Built locally; 64 AArch64 emulator state comparisons pass. Memory/SMP source checks and PSCI AArch64 compilation pass.
- Recorded exact Mach-O disassembly, output checksums and remaining platform blockers in docs/DIZI-INIT-B.md.
- API proxy denial prevents remote Actions dispatch/publication; no new hardware result claimed.

# UniXNU Dizi / Ruan — engineering changelog

This log tracks **hardware-confirmed observations**, separately from
**locally/CI-built but untested images**. A successful GitHub Actions
run alone never upgrades an experiment to hardware-confirmed.

## 2026-10-31

### Hardware-confirmed on Xiaomi Redmi Pad Pro (`dizi`)

- **`flow-b`: all 8 `_arm_init` checkpoints photographed.**
  The device displayed the earlier `ARCH REGS OK` plus
  `1 PROLOGUE`, `2 TBI RETURN`, `3 KC REBASE`,
  `4 CPU DATA`, `5 PE PLATFORM`, `6 TIMER WFE`,
  `7 CPU TOPO` and **`8 THREAD READY`**.
  The final native hook is `0xFFFFFFF0079B3ABC`, after
  `_thread_bootstrap` returned but before the displaced
  `mov x20,x0`. Not proof of a working scheduler,
  `_arm_init` completion or additional CPUs.
  Boot SHA-256:
  `3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c`.
  [Hardware evidence](data/dizi-flow-b-eight-markers-hardware-20261031.json) ·
  [Work handoff](docs/AI-WORK-HANDOFF.md).


- **`arch-b`: passed the six architecture-register checks.**
  The device displayed `XNU ENTRY`, `PRE ALIAS ARMED`,
  `POST SCTLR OK`, `GUARD PASSED`, `TPIDR DONE`, and
  `ARCH REGS OK`. This establishes CPU0 execution at the
  first instrumented `_arm_init` opcode at EL1, with the
  19.2-MHz timer frequency, expected MMU status and cleared
  TPIDR register. It does **not** establish completion of
  `_arm_init` or functional timer interrupts.
  Boot SHA-256:
  `58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`.
  [Hardware record](data/dizi-arch-b-registers-hardware-20261031.json).
- **`deep-b`: reached `ARM_INIT CPU0`.** Prior messages
  included `TPIDR DONE`, and code reached the instrumented
  `_arm_init` entry. This is a checkpoint, not a complete
  bootstrap. [Hardware record](data/dizi-deep-b-arm-init-hardware-20261031.json).
- **Corrected `alias-b`: MMU-on and virtual framebuffer
  output confirmed.** Device displayed `PRE ALIAS ARMED`,
  `POST SCTLR OK`, and `GUARD PASSED`.
  Corrected image SHA-256:
  `ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`.
  The earlier failure at MAIR check #4 was a **mistaken
  source-photo transcription**, corrected with one immediate
  byte. [MMU evidence](docs/DIZI-MMU-ALIAS-B.md).
- **`slot-b` / `fbwalk-b`:**
  a high virtual L2 entry was empty during the pre-MMU
  observation; a direct low virtual framebuffer address was
  not mapped by TTBR0. Neither observation alone demonstrated
  that MMU-on would work. See
  [framebuffer notes](docs/DIZI-MMU-FBMAP-B.md).

### Built and source-verified, **not hardware-tested**

- **`bootpath-b`**: an earlier alternative four-stage
  `_arm_init` trace. Retained for comparison; its last
  marker overwrites earlier ones. Not validated on device.
  [Details](docs/DIZI-BOOTPATH-B.md).
- **SMP preflight**: the SM7435 common XNU reset handler
  was changed to retain the full physical Aff0/Aff1 CPU ID
  instead of collapsing distinct MPIDRs to zero. A source
  preflight checks eight CPU nodes, PSCI SMC and GICv3
  configuration. The read-only PSCI helper can compile but
  is **not linked into the boot image** and has not been
  executed on the device.
  `cpus=1` remains the default; `cpus=2` is an explicit
  experimental option only.
  [SMP validation plan](docs/DIZI-DEEP-SMP-PREFLIGHT.md).
- **Memory audit**: recovery-described RAM (6,061 MiB)
  disagrees with an older reference FDT (7,944 MiB).
  The 43-MiB splash allocation and known TTBR1 tables are
  checked offline. This is **not** a live firmware
  `GetMemoryMap` and must not be used to allocate free
  memory in XNU without runtime ownership checks.

### Not yet working or verified

Finishing `_arm_init`, kernel VM and scheduler bootstrap,
panic/exception diagnostics, timer IRQ delivery, functional
GIC redistributors, PSCI `CPU_ON` of CPU1–CPU7, UART,
USB, storage, GPU, drivers, root filesystem and userland.

The `ruan` variant has not been verified separately.

## Workflow rules

- Only the **existing manually dispatched**
  [MMU A/B workflow](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/xnu-mmu-ab-lab.yml)
  builds and publishes hardware-test variants.
- Latest **hardware-confirmed** variant: `flow-b`.
- Next **hardware-untested** variant: to be selected by disassembling the post-`8 THREAD READY` call path.
- No test is considered hardware-confirmed without a
  device photograph/log showing the exact checkpoint.
- Do **not** turn on secondary CPUs merely because
  `7 CPU TOPO` or `8 THREAD READY` appears.
- Test only through temporary `fastboot boot` with a
  verified recovery path. **Never flash experimental images.**

# UniXNU Dizi / Ruan — engineering changelog

This log tracks **hardware-confirmed observations**, separately from
**locally/CI-built but untested images**. A successful GitHub Actions
run alone never upgrades an experiment to hardware-confirmed.

## 2026-10-31

### Hardware-confirmed on Xiaomi Redmi Pad Pro (`dizi`)

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

- **`flow-b`** adds eight distinct `_arm_init` progress
  checkpoints, preserving general-purpose register state and
  NZCV while replaying the displaced native instructions.
  Boot SHA-256:
  `3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c`.
  The readable Arm64 source has been reassembled and compared
  byte-for-byte to the pinned payload. Two local rebuilds
  matched. [Milestones, risks and test steps](docs/DIZI-FLOW-B.md).
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
- Latest **hardware-confirmed** variant: `arch-b`.
- Next **hardware-untested** variant: `flow-b`.
- No test is considered hardware-confirmed without a
  device photograph/log showing the exact checkpoint.
- Do **not** turn on secondary CPUs merely because
  `7 CPU TOPO` or `8 THREAD READY` appears.
- Test only through temporary `fastboot boot` with a
  verified recovery path. **Never flash experimental images.**

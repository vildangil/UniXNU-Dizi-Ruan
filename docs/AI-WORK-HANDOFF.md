## Continuation session 2026-10-31 — INIT-B locally verified

Read [DIZI-INIT-B.md](DIZI-INIT-B.md) first for the new continuation analysis,
precise hook semantics, hashes and remaining work. Latest physical evidence is
still FLOW-B. INIT-B is **locally built and CPU-emulated only**, not hardware tested.

- Confirmed local baseline main bcd0cf2210c9718240914ab3fc4953fb387f6249 matches remote HEAD.
- Downloaded rolling FLOW-B and checked the full 3e587f8d… hash; inspected exact Mach-O symbols/instructions.
- Added init-b with 16 total stages, relocated BL and ADRP with correct native link/page targets, and persistent two-column output.
- Final G VM CALL is BEFORE arm_vm_init (3B74), deliberately avoiding unsafe post-VM framebuffer writes; no VM-return claim.
- No vector handler or new MMIO/PSCI/page-table writes. cpus=1 and example=true retained.
- Output boot SHA: f093fce1722245c097b6712169130cef63a2a40b7aaf9588aec1e11225af377b.
- Output Mach-O SHA: dbe2c7cdcdf65214d1e3360a0c674f07a91fd41e96487939ab36f944c5eadecf.
- 64 Unicorn native-vs-hook comparisons pass; memory/SMP audits and read-only PSCI helper AArch64 compile pass.
- New artifacts under data/dizi-init-b-* describe LOCAL checks, never additional hardware measurements.
- Installed clang/LLVM 19 without root via signed Debian indices and local package extraction. Saved environment install_script/start_skill and required api.github.com allowlist addition.
- Git over the injected proxy works outside the command sandbox. API CONNECT is denied (403); saving network draft did not apply it. No remote Actions run or new release has been produced. User must apply environment network settings before API dispatch can be retried. No new token requested.
- Native full-XNU source build requires pinned macOS/Xcode runner; prelink runtime qualification, live memory ownership, ADT/platform, GIC/timer IRQ, scheduler/rootfs remain unverified. No speculative subsystem bypass was made.
- Next: restore API access, run existing manual workflow on main with init-b, verify output hash, then request one temporary fastboot boot and photo of both columns. Preserve photographed FLOW-B for rollback.

---

# AI / Work handoff — UniXNU on Redmi Pad Pro dizi
**Updated:** 2026-10-31. **Status:** physical-device `flow-b` reached all eight checkpoints inside XNU `_arm_init`.

**This file is intended for a fresh ChatGPT Work session AND for returning to the original chat.** Read it, current `main`, the data files and the CI/release before starting work. Update this file on every substantial work session, including new code, verified build status, remaining blockers, and the next requested hardware test.

## Project and owner constraints

- Primary repository: https://github.com/vildangil/UniXNU-Dizi-Ruan
- Shared SoC repository: https://github.com/vildangil/UniXNU-sm7435-common
- Historical/reference work only: https://github.com/vildangil/dizi_IpadOS_maybe and the older `ios-sweet` experiment. **Do not transplant/replace UniXNU with ios-sweet or rewrite the project as a hybrid.** Examine historical results only to reuse validated ideas.
- Upstream project: https://github.com/UniXNU/UniXNU .
- Target: Xiaomi Redmi Pad Pro (code `dizi`, Qualcomm SM7435/Parrot). `ruan` unverified.
- User wants a *working UniXNU/XNU boot*, not cosmetic markers or a fake simulated OS; early OS initialization, panics, clock/interrupts, IOKit/rootfs and userland are still major missing milestones. Full boot within one/two chats is a **goal**, not a guarantee.
- **Modify `main` directly. Do not create separate branches, PRs, tag clutter or new one-off workflows.** The owner explicitly removed extra branches. If branch protection blocks a safe direct update, explain the blocker; do not imply the change was merged.
- Existing `.github/workflows/xnu-mmu-ab-lab.yml` is **manual workflow_dispatch only**. Keep it that way. Its `slot-b` default remains the safer option. Add advanced options there, not new workflows. Prefer user-confirmed build and source SHA pins, preserve rollback variants.
- No overwriting known working EDK2 / DarwinBoot / XNU baseline. Keep exact SHA checks for every binary change; verify original ARM64 displaced instructions and all branch/call returns, page-table flags, vector table and register/stack preservation. Avoid false-positive tracer messages.
- Owner runs ONLY temporary **`fastboot boot <image>`** on physical tablet. Never instruct `fastboot flash`/partition erases; keep Android recovery and fastboot functional. The assistant/Work has no physical control of the device and must not claim hardware testing on its own. Do not enable `cpus=2` or call PSCI CPU_ON without explicit approved hardware experiment and secondary CPU data/stack/GIC prerequisites.
- Prefer GitHub Actions artifacts/Releases over sandbox downloads. Rolling release `dizi-xnu-latest-test` uses ONE `Mu-dizi-XNU-LATEST-TEST.img` asset, overwritten only by user-authorized manual builds. Check SHA and run result before claiming a new artifact.
- User speaks Russian; communicate results in Russian, succinctly. Avoid asking questions already answered in this document. Do substantial GitHub work autonomously and then ask for one necessary device photograph/log.
- User specifically requested broader **multi-stage diagnostics in ONE image**, not a new boot for each tiny marker. Preserve readable TEXT output rather than colored framebuffer bars and keep messages visible for photographic capture. Preserve native XNU, not patch arbitrary codes that merely make a message appear.

## Verified CURRENT hardware results — authoritative baseline

Last photographed image in user chat: `/mnt/data/2458.jpg` in the previous conversation only (may not be mounted in new Work chat); authoritative transcription is in
[`data/dizi-flow-b-eight-markers-hardware-20261031.json`](../data/dizi-flow-b-eight-markers-hardware-20261031.json).

The **physically tested `flow-b`** image prints:
```
XNU ENTRY
PRE ALIAS ARMED
POST SCTLR OK
GUARD PASSED
TPIDR DONE
ARCH REGS OK
1 PROLOGUE
2 TBI RETURN
3 KC REBASE
4 CPU DATA
5 PE PLATFORM
6 TIMER WFE
7 CPU TOPO
8 THREAD READY
```
All **eight stage names** are visible in the most recent on-device photograph. The underlying UniXNU EDK2 menu is just old framebuffer contents, **not** evidence of returning to firmware.

The final marker is at native XNU `_arm_init` virtual address **`0xFFFFFFF0079B3ABC`**, before displaced `mov x20,x0`. The native call to **`_thread_bootstrap`** immediately before that site returned. It **does not prove** that the displaced instruction executed, the thread/scheduler works, or any subsequent call or full `_arm_init` finished. **The photograph does not establish the precise point where execution stops.**

`flow-b` boot-v4 SHA-256:
`3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c`.
Embedded Mach-O SHA:
`b740835898ca1be232e733c76af967a66fbe025c3b8e48f34c2febb8f889efc7`.
Payload SHA:
`dbdb592ce93c7ad750874c32423b14d4ffa7499ef54a82b3e880cd7bd73f2c6f`.

GitHub Actions successful manual `flow-b` run:
https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41194255999 .
Rolling release:
https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-latest-test .
At handoff it contains `Mu-dizi-XNU-LATEST-TEST.img` with `flow-b` SHA above.
Always recheck current release: it is a **rolling** asset and may change.

Previous hardware-confirmed checkpoints:
- `alias-b` corrected after a mistaken MAIR transcription: `POST SCTLR OK`, `GUARD PASSED` (native `SCTLR_EL1` write/ISB and post-MMU high VA framebuffer write, native compare guard reached/passed). SHA `ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`. Old `ALIAS GUARD FAIL` was **our own typo** `0x008B` vs real `0x00BB` in MAIR byte.
- `deep-b`: `TPIDR DONE`, `ARM_INIT CPU0` printed. SHA `4acf22fe3b0fb389ccc057b591b7c41fc57e0e0c32eaa246342f34e85c232c45`.
- `arch-b`: `ARCH REGS OK` printed, verifying `CurrentEL=EL1`, `CNTFRQ_EL0=19,200,000`, MMU `SCTLR.M=1`, `TPIDR_EL1=0`, `MIDR` nonzero and bootstrap `MPIDR` affinity 0. SHA `58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`.
- `slot-b` screenshot confirmed TTBR1 L1 C0 / L2 20 candidate entry zero at that instant (`STATUS=2`); `fbwalk-b` confirmed TTBR0 low VA `0xB8000000` was **unmapped** (`STATUS=1`). Kernel instruction and VBAR were mapped by valid executable L2 block from `walk-b`.

Important screenshot-measured register/mapping values:
```
TCR_EL1       0x00000022A51A251A
TTBR1_EL1     0x0000000802F6E000
TTBR0_EL1     0x0000000802F6D000
MAIR_EL1      0x0C0804FF00BB44FF  # BB, never misread as 8B!
VBAR_EL1      0xFFFFFFF0073ED000  # D000, not 0000
SCTLR_EL1 old 0x0000000030D00808
x22           0xFFFFFFF007004000
x23           0x0000000802E04000
TTBR1 L1      0x0000000802F70003
kernel L2     0x0000000803000601  # 2-MiB block
alias L2      0x0000000000000000  # empty before alias-b
framebuffer physical   0xB8000000; display 1600x2560 stride 6400
framebuffer reserve    43 MiB (0xB8000000..0xBAAFFFFF)
framebuffer high VA    0xFFFFFFF004000000
alias block descriptor 0x00600000B8000C0D # AttrIdx3=0 Device nGnRnE, NX, AF, nG
```
The guarded alias modifies ONE L2 entry before SCTLR. It is an instrumentation workaround, not an implemented framebuffer driver or reusable VM allocator.

## Repository code and validation

Current `main` files of interest:
- `board.toml`: **example=true**; native full XNU still intentionally incomplete/blocked by configuration. Default kernel args `-v cpus=1`. Do not set example=false just to force a build without validating hardware integration.
- `feeds.toml`: SoC common pinned to `22a71774c8ebf8ca6f2816bf774ff05d6b96e828`. The common repo may have newer README commits; review the pinned *code*, not blindly its latest main.
- `dts/dizi.dts`, `dts/sm7435-smp.dtsi`, `config/dizi-hardware.json`, `data/dizi-fdt-observed.json`, `ci/check_dizi_memory_map.py`, `ci/check_sm7435_smp.py`.
- `ci/patch_dizi_mmu_flow_b.py`, `ci/dizi_mmu_flow_b.S.in`, `ci/dizi_mmu_flow_b_payload.b64`, `ci/check_dizi_flow_b_source.py`: checked original opcodes, SHA, source assembler equivalence, code cave.
- `ci/patch_dizi_mmu_arch_b.py`, `ci/patch_dizi_mmu_deep_b.py`, `ci/patch_dizi_mmu_alias_b.py`, and prior variants.
- `docs/DIZI-FLOW-B.md` (detailed stage addresses), `docs/DIZI-DEEP-SMP-PREFLIGHT.md`, `docs/DIZI-MMU-ALIAS-B.md`, `docs/DIZI-MMU-BOUNDARY.md`, `CHANGELOG.md`, hardware evidence under `data/`.
- `.github/workflows/xnu-mmu-ab-lab.yml`: manual pinned build+artifact+one-asset release. `.github/workflows/validate.yml`: source-only preflight including memory and PSCI compile. Other workflows build native XNU source and prelink candidate; they do **not** imply a bootable OS.
- The raw Mach-O is 51,941,376 bytes. SHA-pinned Android boot-v4 used for `flow-b` is 68,800,512 bytes. It embeds a FAT volume, prelink Mach-O, EDK2 and DarwinBoot. Never discard known good firmware or use unrelated boot.img sizes blindly.

`flow-b` has eight register/flags-preserving one-opcode hook sites:
```
1 PROLOGUE      0xFFFFFFF0079B3424
2 TBI RETURN    0xFFFFFFF0079B3448
3 KC REBASE     0xFFFFFFF0079B3984
4 CPU DATA      0xFFFFFFF0079B39A4
5 PE PLATFORM   0xFFFFFFF0079B39B0
6 TIMER WFE     0xFFFFFFF0079B39C8
7 CPU TOPO      0xFFFFFFF0079B3A78
8 THREAD READY  0xFFFFFFF0079B3ABC
```
The additional verified zero source cave for that code is `0xFFFFFFF0073F1800..0xFFFFFFF0073F1FF0`; the tracer is 1,163 bytes, with all modified bytes bounded to the cave and eight four-byte one-opcode branches. It saves/restores x0–x18, x30 and NZCV; requires a valid kernel stack. The 8 text markers do not prove those subsystems function.

Candidate **future** sites (from previous arm64 disassembly; independently verify originals and branch layout before editing):
```
0xFFFFFFF0079B3AC8  after machine_set_current_thread
0xFFFFFFF0079B3AD0  after cpu_bootstrap
0xFFFFFFF0079B3AD4  after rtclock_early_init
0xFFFFFFF0079B3AE4  after kernel_startup_bootstrap
0xFFFFFFF0079B3AE8  after timer_call_init
0xFFFFFFF0079B3AEC  after cpu_init
0xFFFFFFF0079B3AF0  after processor_bootstrap
0xFFFFFFF0079B3B7C  after arm_vm_init
```
**These are candidate diagnostic hook sites, not already confirmed executions.** Verify symbolic names and actual instructions with the *exact* pinned Mach-O/objdump, and never interpret an entry marker as completion of the following call.

## SMP / platform reality

SM7435 Parrot DT describes eight CPUs with physical affinities `0x000,0x100,...,0x700`, four E + four P entries. A common SoC XNU reset patch was adjusted to use `MPIDR & 0xFFFF` unconditionally because an earlier `HAS_CLUSTER`-dependent fallback `MPIDR & 0xFF` would alias all eight physical IDs to zero. Source is in the SoC fork, with pin in `feeds.toml`. **Source-level change has NOT been proven in a real secondary-core launch.**

PSCI SMC and GICv3 are in device description, with GICD `0x17200000`, GICR `0x17260000`, redistributor stride `0x20000`, architectural clock 19.2 MHz. `package/Sm7435PsciReadOnly.c` compiles but is NOT executed in current boot image. `cpus=2` exists as manual opt-in only, and **NO secondary CPU has been started or validated**. Do NOT flip the default from `cpus=1` or execute CPU_ON until CPU_DATA, stack, reset vector, entry memory, PSCI conduit, GICR and per-core timer are independently checked and there is an explicit owner-approved physical test.

Recovery memory observations: 6,061 MiB vs old reference FDT 7,944 MiB, discrepancy 1,883 MiB. The old high-1GiB candidate may overlap live firmware/reserved allocations; `GetMemoryMap` at the correct handoff is needed before placing VM state or log memory. The diagnostic framebuffer reserve is 43 MiB. Android-derived DT and firmware ownership are not interchangeable.

## NEXT Work session — do the maximum safe, verified work in one pass

**Priority A — deepen single-core XNU boot beyond `8 THREAD READY`:**
1. Fetch current GitHub state + latest image SHA + hardware JSON. Verify exact Mach-O disassembly, true return addresses, branching and register conventions, locate the next calls and the last safe point prior to first failure; inspect native kernel XNU source if it matches the cache. Do not assume a particular failure or use stale README statements as facts.
2. Implement ONE high-value multi-stage `next-b` or `init-b` diagnostic extending `flow-b` beyond `_thread_bootstrap` across `machine_set_current_thread`, `cpu_bootstrap`, `rtclock_early_init`, `kernel_startup_bootstrap`, `timer_call_init`, `cpu_init`, `processor_bootstrap`, `arm_vm_init` and any actual next control-flow branch **as verified from Mach-O**. Choose safe hook sites and preserve SP, all live GPRs, NZCV, original instructions and return addresses. Prefer non-destructive, *monotonically persistent* screen messages within the verified first 2 MiB high VA GOP alias, plus bounded fault information if safe; do not overwrite UEFI memory map or vector table without verification. Check original addresses and byte limits.
3. Add valuable read-only fault/boot diagnostics where technically safe: `ESR_EL1`, `FAR_EL1`, `ELR_EL1`, `SPSR_EL1`, `VBAR_EL1`, `SP_EL1`/stack bounds, `DAIF`, `TCR/TTBR/MAIR`, boot_args pointer fields, ADT memory reservations; if an actual exception vector logger is implemented, preserve all vector entries and exception return semantics and ensure it cannot recurse. Do not print cached meaningless register values as real fault data. A minimal persistent log is OK only in explicitly validated owned memory.
4. Trace or implement actual early kernel bootstrap after the first failed subsystem, **not only infinite diagnostic markers**. For native kernel problems, prefer source-level proper fixes in the correct UniXNU/SM7435 files over hardcoding one-off binary skips; retain SHA-pinned binary instrumentation for bounded hardware evidence only.

**Priority B — enable genuine kernel progress, not paper checkmarks:**
5. Inspect `board.toml` `example=true`, OS/kernelcache compatibility, `XnuPrelink`, Apple Device Tree vs Qualcomm DT, memory map, `cpu_data`, per-CPU timer/interrupt setup, panic output, mach-o segments/slide/fixups. Determine what actually prevents a working UniXNU kernel. Create testable native build targets instead of merely flipping example=false. Make substantive compatible patches where possible.
6. Verify stable single-core exception/panic path, kernel VM initialization, processor bootstrap, scheduler and relevant IOKit/rootfs requirements in that order. Host tests/CI must distinguish compile/prelink success from boot success. Do not promise complete boot in one turn if platform integration is lacking.
7. Separately, expand a *read-only* PSCI and GICR/ADT audit with source/host tests and a potential future device probe. No PSCI CPU_ON or second-core power-up in this pass unless correct secondary trampoline/CPU_DATA and explicit user permission exist; keep `cpus=1` default. Don't borrow unverified SM8550/sheng register writes.

**Priority C — real deliverables and monitoring:**
8. Make code edits **directly in `main`** in the primary and pinned common repositories; preserve all working paths. Extend the **existing manual** `xnu-mmu-ab-lab.yml` with one new choice, not one more workflow. Leave baseline `slot-b` and tested `flow-b` selectable; no automatic push-triggered hardware experiments. Pin source and output image SHA-256, refuse mismatched inputs, include a JSON audit artifact and a single boot.img.
9. Execute all feasible local/CI tests NOW. If GitHub Actions can be manually dispatched through available authorized tools/Work browser, run the new variant, observe logs until completion, fix compilation/hashing errors and rerun until clean within the active session. If dispatch unavailable, do not falsely claim a run; give the exact click steps and expected SHA. Do not ask the owner to troubleshoot a build before exhausting CI-source checks.
10. Update **this handoff**, `data/` measurements, `CHANGELOG.md`, and concise top-level `README.md`: distinguish *hardware verified*, *CI compiled*, *locally reproduced*, *not yet tested*, *still blocked*. README had historical stale statements and is very long (~91 kB at handoff): improve concise top summary instead of prepending another long repetitive section. Preserve prior hardware evidence and old hashes for rollback.
11. End with exact GitHub commit links, successful run ID(s), release asset + SHA-256 if available, updated handoff link, what was actually fixed vs merely instrumented, remaining blockers and **ONE precise high-value next on-device `fastboot boot` test** with expected markers. If multiple non-device tasks remain feasible, complete them before ending.

**Reality check:** A completely booted UnixNU is not currently proven. It may require significant native hardware enablement and might take many iterations, not automatically two requests. Keep results falsifiable and do not simulate kernel boot or turn `8 THREAD READY` into proof of a scheduler, IRQs, SMP or userland.

**Most recent owner preference:** Ask Work to implement and test as much as possible in one run; user can return to the older GPT chat after Work, and the older chat should resume by reading THIS file plus latest `data/` and GitHub Actions, without reasking previously supplied hardware details.

Full existing workflow build step was subsequently executed locally from immutable fifth-NOSP through every predecessor to INIT-B, including FLOW-B source reproduction, emulator checks and final SHA256SUMS verification. It passed; corrupted FLOW-B input was rejected before producing output. This remains local execution, not a GitHub Actions run.

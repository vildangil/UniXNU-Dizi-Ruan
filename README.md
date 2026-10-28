# UniXNU Dizi / Ruan

Experimental [UniXNU](https://github.com/UniXNU/UniXNU) port for Xiaomi Redmi Pad Pro (`dizi`, Snapdragon SM7435). The `ruan` variant is not separately verified.

**Current stage (2026-10-28):** Physical dizi has successfully executed the
real firmware `CoreExitBootServices` after removing the Windows-only KEP
hook, entered ARM64 `DarwinEnter`, executed a diagnostic Mach-O entry,
and reached the first original `start_first_cpu` instruction. The
subsequent early-XNU `boot_args` and bootstrap page-table checkpoints
were observed through the `_set_mmu_ttb` return, followed by the
**first stackless PINK control-register marker** at
`0xFFFFFFF0073F22B4` (Y408). The next Y432 marker is not visible
on the latest photo; neither TTBR1 completion nor further EL1 register
configuration is yet established by this build.
This is **not** confirmation of successful `msr SCTLR_EL1`, MMU-on
execution, an initialized Darwin kernel, iPadOS, or userland.
All such results are experimental temporary `fastboot boot` tests with
`cpus=1`. EDK2, original source images and working firmware remain
unchanged.

**Releases (cleanup 2026-10-28):** Diagnostic builds now publish
**one rolling experimental [boot.img](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-latest-test)**
under tag `dizi-xnu-latest-test` (one `.img` asset only).
Future successful manual builds replace that asset instead of creating
new timestamped prereleases with `.img`, `.fd` and `.fat`.
Full maps, firmware blobs, hashes and JSON results stay in each
[Actions run](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions)
as short-lived Artifacts. The source run and SHA-256 are recorded in
the rolling release description. The ordinary UEFI baseline and source-only
builds do not overwrite the active XNU test image.
Exactly **23 obsolete prereleases** were deleted via a restricted,
audited one-time workflow; **nine control/milestone releases** were
preserved, including the confirmed NO-KEP EBS build and the recent
MMU comparison images. Git commits, Git tags and the functional EDK2
were not deleted. Old README links to removed historical release assets
may be unavailable; their build records and recorded results remain.
No workflows were enabled on push, and `fastboot flash` is prohibited.

## UniXNU upstream build model

This is a **UniXNU device port**, using the same format-2 project layout as
[UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng) and
[the official device template](https://github.com/UniXNU/UniXNU/tree/main/examples/device).
It is not a fork of the entire `UniXNU/UniXNU` framework and should not
vendor upstream build scripts as an alternative build system.

UniXNU builds its own **patched variant of Apple's open-source XNU**
through the upstream `./unixnu` tool, source feeds, architecture/OS/board
patch series, component archives and prelink stages. There is no separate
fully independent UniXNU kernel implementation. The experimental DIZI
XNU stage1 kernel built earlier from `ios-sweet` is a distinct historical
experiment, not the official upstream UniXNU build pipeline.

| Location | Responsibility |
| --- | --- |
| `board.toml` | SM7435/dizi identity, component selection, firmware and kernel build profile |
| `configs/dizi_defconfig` | DIZI-specific kernel options |
| `feeds.toml` | Pinned preliminary SM7435 common source with ARM CPU/GICv3/PSCI (not XNU-validated) |
| `dts/dizi.dts`, `data/` | Board tree and independently observed hardware facts |
| `patches/xnu/series` | **Only DIZI-reviewed XNU board patches**; currently empty |
| `package/unixnu.toml`, `package/` | Device boot menu and device-specific payload hooks |
| `porting.toml` | Port progress, hardware evidence and open blockers |
| `ci/`, `.github/workflows/build.yml` | Existing standalone Mu-Silicium UEFI smoke build; manual CI |

**Source provenance:** the repository retains historical sheng-derived files
under `scripts/`, `package/` and `patches/xnu/`. Their presence does not
make them validated SM7435 modules. The three sheng-named XNU patches
have been removed from the *active* DIZI patch series; source files have
not been deleted to preserve historical work.

**XNU build gate:** `board.example = true` remains set deliberately.
Selecting an unreviewed sheng/SM8550 SoC feed or iPadOS kernelcache just
to make a native build appear successful would produce the wrong target.
After a pinned SM7435 SoC module, compatible OS profile, ADT,
kernelcache/prelink inputs and platform driver setup have been reviewed,
the native build should use the upstream commands from an external
`UniXNU` checkout:

```sh
./unixnu defconfig dizi_defconfig -D ../UniXNU-Dizi-Ruan
./unixnu status --json -D ../UniXNU-Dizi-Ruan
./unixnu fetch -D ../UniXNU-Dizi-Ruan
./unixnu build kernel -D ../UniXNU-Dizi-Ruan
```

These are **target commands for the completed device profile**, not
commands that are currently expected to build a bootable DIZI kernel.
The existing standalone EDK2 workflow is separate and unchanged.

## SM7435 eight-CPU groundwork

The board now pins [`vildangil/UniXNU-sm7435-common`](https://github.com/vildangil/UniXNU-sm7435-common) at
`98d9b9bd35c530c2c9a4ea338fbabe5c341c005b`. The SoC repo provides a
`sm7435.dtsi` for the eight Qualcomm Parrot CPU MPIDRs, PSCI SMC, GICv3
distributor/redistributors, 19.2 MHz timer, plus a small source-level SMP
patch derived from the SM8550 proof of concept.

The board's `dts/dizi.dts` includes this SoC DTSI and `board.toml` selects
`soc:configs/sm7435.config` and `soc:patches/xnu/series`.
The fork's original SM8550 power and GPU drivers are **not active**.

**This does not boot XNU or bring up seven secondary processors yet.**
`example = true` and `kernel_args = ["-v", "cpus=1"]` remain unchanged.
Dizi DRAM ownership, kernel/ADT handoff, the selected iPadOS ABI, and the
`ArmCpu` secondary-CPU/interrupt path still require validation. In the
current upstream driver, the SMP opt-in flag is still `sheng-smp=1`;
changing boot flags now would not make this hardware-verified.

Sources: [Qualcomm Parrot DTS](https://github.com/LineageOS/android_kernel_xiaomi_sm7435-devicetrees/blob/849a8a76b0959f7e7c12eb67081591248b2f8e7b/qcom/parrot.dtsi),
[observed dizi FDT](data/dizi-fdt-observed.json),
[upstream ArmCpu](https://github.com/UniXNU/ArmCpu/blob/main/ArmCpu.cpp).
No new UEFI build is required for this source-level SoC profile change;
the tested R4 PMIC buttons remain in the separate firmware workflow.

## Ownership

- **Device repository (this repo):** `board.toml`, defconfig, DTS, device evidence, eventual device drivers and boot profile.
- **[Mu-Silicium](https://github.com/vildangil/Mu-Silicium):** EDK2, BootShim, firmware configuration and PMIC/SPMI.
- **[UniXNU](https://github.com/UniXNU/UniXNU):** generic boot manager, DarwinBoot and shared components.

The checkout was initially derived from `UniXNU-sheng` (SM8550). Its drivers, MMIO values, firmware and iPadOS-specific settings must not be used on SM7435. Native XNU builds remain blocked pending device-specific verification.

## Experimental patched XNU source build (public macOS runner)

[Manual XNU workflow](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/xnu-source-sm7435.yml) compiles the **real upstream UniXNU-patched XNU source**, not the legacy ios-sweet stage1 shim and not EDK2. Trigger **Run workflow** or post exactly `/run-dizi-xnu` as repository owner on [the build-control PR #1](https://github.com/vildangil/UniXNU-Dizi-Ruan/pull/1). It has **no push trigger**.

The workflow pins the upstream UniXNU source and the `sm7435` SoC fork. Its CI-only copy of the board selects the upstream iPadOS 17.7.11 source ABI for compile testing and temporarily disables the `example` guard. **The committed device manifest remains an unverified example**, with `cpus=1`; this test does not assert compatibility with a device kernelcache. It uses the upstream `kernel.build` function but **does not call `kernel.prelink`** because a reviewed dizi iPadOS kernelcache is not available.

If successful, the job publishes a **source-only unprelinked ARM64 Mach-O** under `xnu-dizi-sm7435-UNPRELINKED-<runid>` plus `BUILD-RESULT.json` with SHA-256 and file size. This cannot be booted by itself and is not an Android/Apple dualboot image. Errors produce redacted text logs in a separate artifact, including the first source/patch/compiler failure. The pinned SM7435 SMP patch is a source-level adaptation, not hardware verification.

## Diagnostic Apple ADT parse experiment (eight CPU topology)

### Loader Not Found: root cause (device photos, 2026-10-27)

The Dizi hardware confirmed the unprelinked XNU and ADT boot-v4 probe
reaches the UniXNU menu, but pressing the XNU entry returned
`Not Found` (not `Aborted`). The ADT generator succeeded; **the actual
problem was the FAT pathname**. The menu lived at
`EFI/UniXNU/unixnu.toml`, and its entry specified the relative
`Payloads/kernel.macho`. UniXNU's `Config.c` resolves relative paths
using `MakePath(UNIXNU_CONFIG_DIR, Path)`; the normalized target was
`/EFI/UniXNU/Payloads/kernel.macho`. The original probe image incorrectly
stored it at `/Payloads/kernel.macho`, so DarwinBoot returned EFI_NOT_FOUND
before reading either kernel or ADT.

The corrected manual test stores both `kernel.macho` and
`kernel.macho.adt` inside `/EFI/UniXNU/Payloads/`, verifies FAT readback
byte-for-byte, and uses `ci/xnu-adt-probe-menu.toml` with an accurate
fail-closed warning. This fixes only file discovery, NOT XNU kernel entry,
memory ownership, prelink, system/root or SMP. The known-good standalone
UEFI build and hardware PMIC buttons are untouched.


The [manual ADT parser probe](.github/workflows/xnu-adt-parse-probe.yml)
extends the successful DarwinBoot loader smoke test. A photo of the preceding
loader probe showed `XNU loader probe ... returned: Not Found`, which is
consistent with DarwinBoot requiring `Payloads/kernel.macho.adt` next to
the raw `Payloads/kernel.macho`. The previous probe deliberately omitted it.

The current corrected workflow:
- Clones the pinned upstream UniXNU DT-to-ADT converter and pinned
  [SM7435 SoC profile](https://github.com/vildangil/UniXNU-sm7435-common).
- Stages a **CI-only** memory node from a previously observed 3 GiB upper
  FDT DRAM bank (0x8c0000000). The memory bank is real FDT evidence, but its
  safe runtime ownership is **NOT verified**; it is never added to the device
  tree used by the normal firmware build.
- Generates an Apple ADT reference containing 8 CPU MPIDRs, 4E+4P clusters,
  PSCI and the SM7435 GICv3 settings, then checks that ADT structurally.
- Adds the `.adt` sidecar to the separate diagnostic FAT32 initrd.
- **Patches DarwinBoot in the disposable CI checkout to abort intentionally**
  before `ReadBootVideo`, `AllocateWindow`, `ExitBootServices`, or a kernel
  branch. Success on device means it now reports `Aborted` after ADT
  parsing rather than `Not Found`. It is NOT a successful XNU boot.

Use `/run-dizi-adt-probe` as the repository owner on
[control PR #1](https://github.com/vildangil/UniXNU-Dizi-Ruan/pull/1),
or dispatch the workflow manually. No CI builds run after `push`.
A successful build publishes a separately tagged `*-FAIL-CLOSED.img`
intended only for temporary `fastboot boot`; never flash it.

**Blockers to actual kernel entry** remain a prelinked and ABI-compatible XNU,
a verified XNU/EFI-owned memory window, a reviewed on-device ADT/identity,
appropriate trust/security inputs and the first XNU entry checkpoint.
Do not remove the fail-closed patch until those are checked.

## FIRST XNU entry on hardware: firmware synchronous exception (2026-10-27)

#### Only first stackless MMU marker visible on physical dizi (2026-10-28)

Corrected review of the new [photo from NO-SP build
#40700727875](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40700727875):
after rotating the image and comparing stripe Y offsets, the old
MAGENTA/GREEN/WHITE/CYAN and five early bootstrap stripes are visible,
and **PINK Y408 appears**, but **ORANGE-RED Y432 and the other four new
stripes Y456..528 are NOT visible**. An earlier statement in this
README incorrectly claimed all six were visible; this is corrected.

The Y408 marker is the **only one of six** modified to avoid SP
access in this particular A/B build. It is reached from the branch at
`0xFFFFFFF0073F22B4` before replaying the original AND and returning
to the original `msr TTBR1_EL1` at `0xFFFFFFF0073F22B8`.
The next `0xFFFFFFF0073F22BC` hook still enters an SP-based
trampoline whose first instructions touch `[sp]` before drawing.
The photo therefore cannot distinguish a failure during TTBR1 write
from a stack-access fault inside that second probe or the clobbering
side effects of the first no-SP probe. No ESR/FAR/ELR collected.

A new tightly controlled [second-only no-SP patch](ci/patch_dizi_second_mmu_stackless.py)
and [owner/manual-only workflow](.github/workflows/xnu-mmu-two-nosp.yml)
[Actions #40727839823](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40727839823)
**passed all 28 CI steps**. Independently verified Android boot-v4
`Mu-dizi-XNU-MMU-TWO-NOSP-HIGH-RISK.img` (68,800,512 bytes)
SHA-256 `d0905d2913b4880d69ec99af014b9a2549e3f42e0ed44bbb43d377244bf1fd69`.
Its embedded FAT32 and Mach-O byte-for-byte match the archived inputs;
Mach-O SHA-256 is `d88862b4d30fd444ad46ab7d876c2f716b1e745a3875fce885e34b1b823430d1`.
The **single-asset rolling prerelease**
[Latest test image](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-latest-test)
was updated, replacing the previous test image, with no extra prerelease.
This new image has NOT yet been tested on real hardware.
The A/B test keeps the first pink marker byte-identical and replace **only** the
second Y432 marker with no-SP direct GOP writes; all four later
stack-based probes and original TTBR1/SCTLR/ISB remain untouched.
A local reproducibility test on the exact source Mach-O verified
patched SHA256 `d88862b4d30fd444ad46ab7d876c2f716b1e745a3875fce885e34b1b823430d1`.
The new image has **not yet been tested on hardware**.
Stackless diagnostics still clobber x9-x11 and NZCV, so no native
XNU boot success may be inferred from color alone.


#### Six register stages not visible on hardware; first-stage SP differential (2026-10-28)

The physical photo of
[run #40649020254](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40649020254)
shows the old FIVE colored XNU bootstrap bands including PURPLE
`AFTER_SET_MMU_TTB` Y384, but **NONE** of the six new bands at
Y408,432,456,480,504,528. The last supported original-code point is
`0xFFFFFFF0073F22AC` (replayed `mov x30,x19` in purple stub).
The next instruction at `+0x4` is `add x0,x25,#0x1000`; the next hook
at `+0x8` (`0xFFFFFFF0073F22B4`) branches to the first new probe.

**Key test confounder:** the five successful prior marker trampolines do
not reference SP; all six new ones start with `sub sp,sp,#48` and
`stp x9,x10,[sp]` **before any framebuffer writes**. That makes
the missing new stripes potentially caused by an invalid/unmapped early
XNU stack rather than by failure of TTBR1 setup itself. This remains
a hypothesis, not a proven stack fault (no ESR/FAR/ELR captured).

A differential [SHA-pinned copy patch](ci/patch_dizi_first_mmu_stackless.py)
removes SP references **only from the first new pink marker at Y408**,
replays the exact original `and x0,x0,#0xffffffffffff`, then branches
to `0xFFFFFFF0073F22B8`. The next five probes, and original TTBR1,
SCTLR and ISB MSRs remain untouched. The replacement follows the
earlier successful stackless diagnostic convention of clobbering
x9/x10/x11 and NZCV; it is not a general-purpose kernel fix.
Local disassembly checked all instructions and exact 84-byte replacement.
[Manual-only CI #40700727875](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40700727875)
**passed 27/27 steps** and published a [separate NO-SP HIGH-RISK release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-mmu-first-nosp-40700727875-1).
Verified exact boot-v4 `Mu-dizi-XNU-MMU-FIRST-NOSP-HIGH-RISK.img` (68,800,512 bytes)
SHA256 `ceb970d09e05aeff9e09293528d6193a87bf760c96a6e222766df6e73e249620`.
FAT32 kernel SHA256 `5d5666cdb13c64665cb393676806d02a38972660e89cb02547059032c6b40fba`
matches `XNU-FIRST-MMU-NOSP.json`; the first stub is stackless and the
other five probes are unchanged. No hardware test yet.
It uses [xnu-mmu-first-nosp.yml](.github/workflows/xnu-mmu-first-nosp.yml).
No production EDK2 edit, no push, no flash, cpus=1 only.
**Not yet tested on hardware**.

#### Six SP-saving MMU register checkpoints all absent on hardware (2026-10-28)

The user booted the separate [six MMU register checkpoints build
#40649020254](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40649020254)
and supplied a photograph. The previously verified five RED/YELLOW/
GREEN/BLUE/PURPLE bands through return from `_set_mmu_ttb` are visible,
but none of the SIX new Y408..536 checkpoints can be distinguished.
The instrumented copy was checked against the CI JSON and instructions;
this is **not** evidence of MMU-enable completion, nor conclusive proof
of a fault in any particular system-register instruction.

A meaningful difference is that all SIX new stubs start with
`sub sp,sp,#48; stp x9,x10,[sp]`, whereas the previous five
hardware-proven stage stubs make direct physical GOP writes without
accessing the current SP. The current SP's ability to support those
new stores has NOT been demonstrated. Other differences including
diagnostic register clobber and execution-path issues remain possible.

A new [SEVEN checkpoint stackless comparison script](ci/patch_dizi_xnu_mmu_stackless_compare.py)
and [manual-only workflow](.github/workflows/xnu-mmu-stackless.yml)
[Actions #40700771901](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40700771901)
**passed 26/26 steps**. A separate
[NO-KEP HIGH-RISK release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-mmu-stackless-40700771901-1)
contains the byte-verified Android boot-v4
`Mu-dizi-XNU-MMU-STACKLESS-HIGH-RISK.img` (68,800,512 bytes),
SHA256 `e89e4c9c9b9a70ad4b170cad8899efad57fc219ab7b556b114d10084b3663021`.
FAT32 ramdisk matches boot-v4 byte-for-byte; embedded Mach-O copy
SHA256 `b47586b661f759172e4e3e065cda404b19185e959bb1cdf625c1e21383f71e39`
was independently checked against `XNU-MMU-STACKLESS-COMPARE.json`.
The seven branch targets are re-read and all point to their recorded stubs.
**Not hardware tested yet.** They apply to the SAME pinned 5-band Mach-O SHA and put the first new
checkpoint at `0xFFFFFFF0073F22B0`, directly after the observed purple
return at `0xFFFFFFF0073F22AC`. These stubs do not read/write SP,
but **they deliberately clobber x9-x11 and NZCV**, just like the
previous hardware-proven marks, and must not be considered production
instrumentation. All original TTBR1/MAIR/VBAR/SCTLR and ISB instruction
bytes remain at their original addresses. There is no hardware result
for this new comparison yet, no new CPU activation, no production
firmware changes, and the explicit temporary fastboot boot-only
constraints remain unchanged.

#### Five early bootstrap markers all visible on physical dizi (2026-10-28)

The user tested verified HIGH-RISK
[boot #40647473480](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40647473480).
Photograph shows the original MAGENTA/GREEN/WHITE/CYAN markers plus
**ALL five new colored nine-row bands**: RED Y288, YELLOW Y312,
GREEN Y336, BLUE Y360, PURPLE Y384. The independent exact
`XNU-BOOTSTRAP-STAGES.json` lists the final purple hook at
`0xFFFFFFF0073F22AC`, first instruction after the real
`bl _set_mmu_ttb` at `0xFFFFFFF0073F22A8`. Thus at least
the returned control-flow edge from `_set_mmu_ttb` was reached.
The screenshot does **NOT** clearly show the expected ORANGE Y260
pre-`SCTLR_EL1` band; its execution is not yet verified.

The disassembled code between the purple hook and
`msr SCTLR_EL1,x0` at `0xFFFFFFF0073F2350` performs
`msr TTBR1_EL1`, `msr MAIR_EL1`, `isb`, `tlbi`,
`ic iallu`, `msr VBAR_EL1`, and SCTLR-value synthesis.
**Do not claim that XNU has enabled its own MMU.**
Earlier five physical-GOP stage stubs clobber x9-x11 and NZCV;
until instrumented independently, this disturbance is a potential
contributor to the later hang and is NOT ruled out.

A new independent
[manual-only six-stage workflow](.github/workflows/xnu-mmu-reg-stages.yml)
[Actions #40649020254](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40649020254)
**passed all 26 CI steps**, and published the separate
[HIGH-RISK six-stage release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-mmu-reg-stages-40649020254-1).
Boot image `Mu-dizi-XNU-MMU-REG-STAGES-HIGH-RISK.img`
(68,800,512 bytes) has independently verified SHA256
`0ee0b86c6a44138d5f14ec74c59f7de10924ba9571b2487d8fadc38a993a9ca1`;
FAT32 matches the boot-v4 ramdisk byte-for-byte and its instrumented
51,941,376-byte Mach-O SHA256
`cc4da0da3850c23d1498c343c836387f4d68342e9f0ed8da4ae4b079c8a693e7`
matches `XNU-MMU-REGISTER-STAGES.json`. **Not yet hardware tested.**
It patches a separately SHA-pinned COPY of the five-band Mach-O with six
stack-preserving checkpoint stubs. They save/restore x9-x12 and NZCV,
replay the exact replaced instruction and return to the original +4;
`SCTLR_EL1` and subsequent `isb` remain unchanged. It adds
six colored bands Y408, Y432, Y456, Y480, Y504, Y528 around
TTBR1/MAIR/TLBI/VBAR, without touching the previous verified EDK2.
This has NOT yet been tested on hardware. NO XNU success, no other CPU
bring-up, manual confirmation and fastboot boot-only remain in force.

#### No orange indicator in first pre-MMU hardware test (2026-10-28)

The physical test of [pre-MMU run #40646191965](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40646191965)
did **NOT** show the expected orange checkpoint. Prior CYAN in
`start_first_cpu` had been hardware-confirmed separately; no new
hardware result demonstrates progress toward `msr SCTLR_EL1,x0`.

Independent inspection of the actual FAT32 Mach-O exposed a display
diagnostic error: the old "orange" stub at `__start+0xC0` writes
ARGB **`0xFF00A5FF`**, not the intended orange **`0xFFFFA500`**.
Consequently, "no orange color" is not proof that execution failed
before `0xFFFFFFF0073F234C`; the old stub could have shown purple.
The code is also downstream of boot_args dereferences, bootstrap
stack initialization, 64-KiB page table zeroing, page table descriptor
construction and a call to `_set_mmu_ttb`. The first native entry
alone proves none of those stages completed.

New pinned-copy [five-stage diagnostic](ci/patch_dizi_xnu_bootstrap_stages.py)
and [manual-only workflow](.github/workflows/xnu-bootstrap-stages.yml)
[Actions #40647473480](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40647473480)
**passed all 25 CI steps**, and published a separate
[HIGH-RISK five-band release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-bootstrap-stages-40647473480-1).
Boot-v4 `Mu-dizi-XNU-BOOTSTRAP-STAGES-HIGH-RISK.img`
(68,800,512 bytes) independently SHA256 verified
`5b49b20f48675e2ead18e2da276795ab46922ee13a2b25a84e2be0270657ea01`.
FAT32 readback confirms the patched 51,941,376-byte Mach-O at
`0x101200` hashes to
`94947ff724ec85b005e7b6241e625867dadf5c10b053a1b2ae5f4f75e8b4a1d3`
and matches `XNU-BOOTSTRAP-STAGES.json`. **This image has not yet
been tested on real hardware.**
It corrects the ORANGE ARGB bits and adds physical-GOP stackless
checkpoints that replay their original displaced instructions:
RED Y288 before first `boot_args` load, YELLOW Y312 after boot args
reads, GREEN Y336 after initial page table zero loop, BLUE Y360
at `common_start` entry following mapping setup, and PURPLE Y384
after `_set_mmu_ttb` returns. There is no proof yet which of these
will execute on real hardware. Source Mach-O remains unchanged; no
production EDK2 source, sm7435 drivers, push triggers or partitions
are modified. This remains HIGH-RISK temporary fastboot boot only.

#### First native start_first_cpu opcode confirmed on physical dizi (2026-10-28)

Physical dizi test of [HIGH-RISK CYAN NO-KEP build
#40644853194](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40644853194):
the user reports that the new **CYAN Y240..248 stripe is visible**,
after the previously confirmed WHITE Mach-O entry stripe.

The CYAN trampoline is entered only through the native
`start_first_cpu` VA `0xFFFFFFF0073F205C` (first instruction
`msr OSLAR_EL1, xzr`), and its first instruction REPLAYS that original
MSR before the volatile framebuffer writes. This confirms the path
reached the first native XNU startup instruction on real hardware.
The diagnostic subsequently branches to `start_first_cpu+4`;
however, completion of the remaining native initialization has
**not** been observed. No proof yet of page-table construction or
successful XNU-owned EL1 MMU enable.

The next independent [manual-only pre-MMU workflow](.github/workflows/xnu-pre-mmu-no-kep.yml)
[Actions #40646191965](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40646191965)
**passed 24/24 GitHub Actions steps** and published the
[pre-MMU orange HIGH-RISK release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-pre-mmu-no-kep-40646191965-1).
The verified `Mu-dizi-XNU-PRE-MMU-NO-KEP-HIGH-RISK.img` is 68,800,512
bytes, SHA256 `97a5ce129247f45c5be0aec7aae478e009c76a7bdbb55660988b6b4931e6e26a`.
The pinned copied Mach-O SHA256 is
`de29ffc668de50ddef7fe4ac2f49b992eb3531512e750ee81143e1ab46fd7d9e`.
CI and local artifact checks confirm the original `SCTLR_EL1` and `ISB`
instructions are unmodified, and the new trampoline is 84 bytes.
This image **has not been hardware tested yet**. It uses a third SHA-pinned COPY and the [orange checkpoint](ci/patch_dizi_xnu_pre_mmu.py).
At `0xFFFFFFF0073F234C` the original `movk x0,#0x593d` is
replayed in a checked empty cave. ORANGE Y260..268 is painted and
execution returns to the **unmodified** `msr SCTLR_EL1,x0`
at `0xFFFFFFF0073F2350`, followed by the unmodified `isb`.
Orange will mean the native kernel reached the **point immediately before
enabling its own MMU**; it will NOT prove the MMU-enable MSR completed.
Existing NO-KEP, explicit POWER confirmation, cpus=1, manual CI
and fastboot boot-only safety constraints remain unchanged.
No driver changes or working EDK2 changes.

#### First live XNU Mach-O instruction confirmed on dizi (2026-10-28)

The device test of the independent [NO-KEP white-entry build
#40643799207](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40643799207)
**displayed the WHITE Y220..229 stripe**. The image's first ARM64
Mach-O entry instruction branches to the SHA-pinned 40-byte payload
at `0xFFFFFFF0073F04C8`; its direct physical GOP stores then execute.
Because the marker is only in the copied Mach-O payload after
`DarwinEnter` disables EL1 MMU and performs the entry branch,
this is the first hardware confirmation of executing code from the
experimental Mach-O image on Redmi Pad Pro.

**This does not demonstrate** the native `start_first_cpu` instruction,
XNU's own MMU re-enable, VM, interrupts, userland, or working iPadOS.
The WHITE trampoline unconditionally branches to native
`start_first_cpu` VA `0xFFFFFFF0073F205C` after drawing, but the
target's execution has not yet been observed.

For the next experiment, verified original native first instruction is
`0xD510109F` (`msr OSLAR_EL1,xzr`), then
`0xD5034FDF` (`msr DAIFSet,#0xf`) and
`0xAA0003F4` (`mov x20,x0`). The independent pinned COPY patch
[ci/patch_dizi_xnu_start_first_cpu.py](ci/patch_dizi_xnu_start_first_cpu.py)
hooks only the first native instruction to a verified unused code cave
at entry +0x80. It replays the first original word, paints
**CYAN GOP rows Y240..248** and branches to the original next
instruction. It leaves the WHITE entry marker and original
source Mach-O intact. This adds a specific native-start checkpoint
without skipping the existing native first instruction.

[Manual-only build #40644853194](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40644853194)
**passed 23/23 CI steps** and published a separate
[HIGH-RISK CYAN native-start image](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-native-start-no-kep-40644853194-1).
The exact boot-v4 `Mu-dizi-XNU-NATIVE-START-NO-KEP-HIGH-RISK.img`
is 68,800,512 bytes, SHA256
`d1adc626d7d617771300e5003bee2d8b0163baee7d518b1c7e336714eec50abb`.
Its FAT32 contains the patched 51,941,376-byte Mach-O at offset
`0x101200`, SHA256 `1d200a2e544f0bb766081f9a2682df24fd39cf30873278ec2d78b2725eb8251d`,
matching the independently produced 44-byte trampoline test.
**This new image has not been hardware tested.** It uses [xnu-native-start-no-kep.yml](.github/workflows/xnu-native-start-no-kep.yml);
there is no push trigger. Like the previous image, this is still a
HIGH-RISK real kernel handoff with an unverified RAM map and ADT,
explicit POWER confirmation, cpus=1 and temporary `fastboot boot` only.
The physical result of this new CYAN probe is not yet known.

#### First real DarwinEnter reached on dizi (2026-10-28)

The **HIGH-RISK** image from [Actions #40642424939](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40642424939)
was tested on physical dizi. Photograph shows **MAGENTA Y172..195**
(the direct framebuffer mark immediately AFTER EFI_SUCCESS EBS)
and a very wide **GREEN top Y0..159** painted by
`UniXNU/DarwinBoot@3325e352/DarwinBootPkg/Driver/Entry.S` inside
`DarwinEnter` **BEFORE cache/MMU disable and `br x1`**. The system
then displays a static image; no kernel-origin diagnostic or verified
Mach-O instruction execution is observed.

This proves entry into the DarwinEnter ARM64 assembly and that the previous
KEP EBS fault is not blocking this handoff. It **does not prove** that
MMU disable, `br x1` or XNU startup succeeded. Do not infer cause of a
subsequent hang from the image alone.

A new independent **manual-only HIGH-RISK**
[opcode-proof workflow](.github/workflows/xnu-first-opcode-no-kep.yml)
[Actions #40643799207](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40643799207)
**passed 22/22 CI steps** and published the independent
[HIGH-RISK NO-KEP first-opcode release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-first-opcode-no-kep-40643799207-1).
Exact boot-v4 artifact `Mu-dizi-XNU-FIRST-OPCODE-NO-KEP-HIGH-RISK.img`
(68,800,512 bytes) SHA-256 `931bef2e1640577352113734f72bf6969a94002308dc1e389e8e340064c29d42`
was rechecked outside GitHub Actions. The FAT32 copy of
`/EFI/UniXNU/Payloads/kernel.macho` independently hashes to
`867b82d1445ebf6c505dbad92345efa60a34a01cad37dde3b375f103691160eb`
and its Mach-O entry/trampoline bytes were read back successfully.
**This image has NOT been tested on physical hardware.**
It patches a SHA-pinned **COPY** of the original prelinked Mach-O:
entry VA `0xFFFFFFF0073F0488`, original opcode `0x140006F5`
branching to `0xFFFFFFF0073F205C`. The byte-verified zero padding at
entry + `0x40` receives a short 40-byte stackless ARM64 trampoline.
The original branch is retained at the end. Its direct GOP physical-memory
stores paint a **WHITE Y220..229** stripe only if execution enters the
instrumented Mach-O after the MMU-off branch. WHITE proves patched entry
code ran, **not** that original XNU code reached an initialized state.
No automatic start, no 7 extra cores, no push trigger; temporary
`fastboot boot` only, no flashing. Working UEFI and sm7435-common untouched.
Original kernel SHA `49eed545945df805b6f004eaecc496575072184c6335efea1f5b11ea50feda42`.

#### First verified EXIT_BOOT_SERVICES success on physical dizi (2026-10-28)

**Hardware confirmed** with the manually built
[NO-KEP run #40641321399](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40641321399),
booting `Mu-dizi-XNU-EBS-NO-KEP-NO-XNU.img` temporarily:

- the device shows a full **MAGENTA** Y0..79 strip after option 2
- `ci/patch_darwinboot_ebs_stage_probe.py` paints that full strip only
  in `if (!EFI_ERROR(Status))`, *after* the real `ExitBootServices` returned
- there is **no** prior `Synchronous Exception` text
- runtime `gBS->ExitBootServices` is **`0x00000000FEFCF434`**
- first 32-bit instruction **`0xA9BC53F3`** and next words
  `A9015BF5 F90013F7 B00000D6` at relative offsets
  `0,+4,+8,+0x70` exactly match the **same CI** `DxeCore.disassembly.txt`
  (`CoreExitBootServices` RVAs `0x1434,0x1438,0x143C,0x14A4`)
- runtime DXE Core base candidate is `0xFEFCF434 - 0x1434 = 0xFEFCE000`,
  correctly 4-KiB-aligned

**This is the first confirmed successful UEFI EBS boundary on dizi.**
The 12 top cells were overwritten by the final MAGENTA rectangle (and
therefore cannot be interpreted as missing DXE Core stage execution).
This NO-XNU build HALTS after EBS and **does not execute XNU**.

The next _separate_ [opt-in high-risk real-entry workflow](.github/workflows/xnu-first-entry-no-kep.yml)
[Actions #40642424939](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40642424939)
**completed successfully (21/21 steps)** and published a [separate
HIGH-RISK first-entry release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-first-entry-no-kep-40642424939-1).
Exact boot-v4 `Mu-dizi-XNU-FIRST-ENTRY-NO-KEP-HIGH-RISK.img`
(68,800,512 bytes) SHA-256 `57ae6c3511e05a1e2ce98a16d1c71874ab7c1c939bb7bbdf4b54c7f2c1a98836`
was verified against GitHub Actions artifact checksum. The compiled
`BdsDxe.efi` passes the exact old KEP fault fingerprint absence test.
**No hardware XNU entry has been observed with this image yet.**

It retains NO-KEP while using the existing explicit-confirmation first-entry
menu and original `DarwinEnter`. Post-EBS magenta Y172..195 and pre-kernel
DarwinEnter green top stripe will help localize the next hang. The green bar
is still **not proof of XNU instruction execution**; no seven extra CPUs
are started. The kernel's ownership of its RAM window, memory map and ADT
remains unverified: test is high risk, RAM-only, **fastboot boot only**.
No working firmware, partition, or historical repository was modified.

#### Root cause isolated: Project-Silicium Windows KEP EBS hook (2026-10-28)

From the actual [four-word hardware photo / Actions #40639206923](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40639206923):

| Runtime evidence | Value |
|---|---|
| `gBS->ExitBootServices` | `0xFC366E3C` |
| sync exception `ELR`/PC | `0xFC366EAC` |
| opcode at +0 | `A9BD53F3` |
| opcode at +4 | `F9000BF5` |
| opcode at +8 | `A901FBFD` |
| opcode at +0x70 | `B900012A` = `str w10,[x9]` |
| retained DXE Core marker cells | all uncolored |

The **SAME build** `SILICIUM_UEFI-dizi-EBS-FOUR-WORDS.fd`
contains an inner FVMAIN in an LZMA-guided-compressed section.
After decompression, the **only matching FOUR-word pattern** across that
~6 MiB FV is in `BdsDxe.efi` (FFS
`6d33944a-ec75-4855-a54d-809c75241f6c`, BdsDxe UI string).
The image's PE32+ ARM64 `.text` at RVA **`0x3E3C`** matches the
function entry, with faulting store at **RVA `0x3EAC`**. This yields
a perfectly page-aligned live BdsDxe base **`0xFC363000`**.
The previous assumption that this PC was in `DxeCore` was incorrect.

The source of the function was identified in the pinned
`Mu-Silicium@39fbbc20885325044cfeaf8428efb7267e0bbe35`:
`Silicon/Silicium/SiliciumPkg/Library/KernelErrataPatcherLib/`.
Its `ReadyToBootHandler` substitutes `gBS->ExitBootServices` with
`KepExitBootServicesHook`. That calls `PatchTransferToKernel`,
which executes an unsafe-for-this-loader ARM64 branch patch via
`ARM64_INSTRUCTION(mTargetInstructionAddr) = ...` at the recorded PC.
The exact translation/permission exception subtype still requires ESR/FAR;
do not claim memory protection or target validation conclusively.

A **separate CI-only NO-XNU test** prevents the Windows
`KernelErrataPatcherLibConstructor` from registering this hook,
without touching the working Mu-Silicium source checkout or bypassing
EDK2's normal `CoreExitBootServices` callbacks. Its pinned-source
patch is [ci/patch_dizi_disable_kep_for_ebs.py](ci/patch_dizi_disable_kep_for_ebs.py),
plus [compiled BdsDxe check](ci/check_dizi_kep_bds_image.py).
Manual-only [workflow](.github/workflows/xnu-ebs-no-kep.yml)
[Actions #40641321399](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40641321399)
**passed 23/23 steps**, and [the NO-KEP NO-XNU test release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-ebs-no-kep-40641321399-1)
contains the separately built 68,800,512-byte
`Mu-dizi-XNU-EBS-NO-KEP-NO-XNU.img`, SHA256
`148f46dbccb71cc2606bfa293aa573f9514b1064dc721df8423bddd1ed292eff`.
The same run archived `bds-kep/BdsDxe.efi` and
`KEP-BYPASS-CHECK.json`, confirming `old_kep_four_word_fingerprint_absent=true`
and `old_kep_four_word_fingerprint_offsets=[]` in the compiled PE.
It does not enable `push`, Windows patching, XNU kernel entry or
`fastboot flash`. Only a new **on-device** temporary `fastboot boot` can
confirm that the EBS exception is eliminated; passing CI does not
prove this yet.

#### Live EBS instruction mismatch confirmed on Dizi (2026-10-28)

The **fixed B800 framebuffer** build
[Actions #40637451443](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40637451443)
was tested on a real Redmi Pad Pro. All 12 outlined dark-navy cells remain
uncolored even though DarwinBoot confirms the live GOP B8000000 address.
Crucially, the new on-screen instruction read proves:

- `gBS->ExitBootServices` = **`0x00000000FC368E3C`**
- actual 32-bit ARM64 opcode at that pointer = **`0xA9BD53F3`**
- synchronous exception PC = **`0x00000000FC368EAC`** = EBS + `0x70`
- compiled **same-test** DxeCore.dll `CoreExitBootServices` at
  `RVA 0x1434` begins **`0xA9BC53F3`** (STP with 0x40 stack frame)

The first-instruction **mismatch is real**. It does NOT alone prove a
different image, because this STP encoding appears elsewhere in DXE code;
compare at least 3 consecutive 32-bit words with the same CI PE before
attributing the runtime handler to a specific compiled function. Since
the stage marker was not observed even after the framebuffer correction,
do not claim callbacks, the timer or XNU are responsible yet.

A new isolated [manual-only four-word probe](.github/workflows/xnu-ebs-four-words.yml)
reads and shows EBS machine words at offsets `0,4,8,0x70` before EBS is
called, using direct framebuffer glyph stores. No flash, no EBS service
bypass, no XNU entry, and **no changes to the working EDK2**.
[Build #40639206923](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40639206923)
**passed all 21 CI steps**; the standalone verified Android boot-v4
`Mu-dizi-XNU-EBS-FOUR-WORDS-NO-XNU.img` is in
[release dizi-xnu-ebs-four-words-40639206923-1](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-ebs-four-words-40639206923-1).
SHA-256 `b787b38d8b1475a909b31062f79ca6dc7a8625831381820061c1f293b706ab97`.
This build has **not yet been tested on device**. Y244=EBS pointer,
Y276=first opcode, Y308=FOUR adjacent 8-hex groups ordered
`[EBS+0, EBS+4, EBS+8, EBS+0x70]`. Use
[ci/match_dizi_ebs_fingerprint.py](ci/match_dizi_ebs_fingerprint.py)
with the same run's `DxeCore.disassembly.txt` and `DxeCore.map` after
reading the new photograph; do not call a single STP prologue an exact match.

#### Hardware-confirmed DXE stage framebuffer mismatch (2026-10-28)

On the latest dizi photo, DarwinBoot's actual debug output clearly reports
`video base=0xB8000000 row=6400 width=1600 height=2560 depth=32`.
Earlier `ci/patch_dizi_dxecore_ebs_trace.py` incorrectly writes **DXE Core**
colored stage pixels to a hardcoded **`0xB0000000`**, a 128-MiB mismatch.
The 12 outlined navy calibration cells created by **DarwinBoot** DO appear
on-screen, but no DXE Core cell changes color. This means the old visual
evidence **cannot** distinguish failing DXE callbacks from pixels written
to the wrong framebuffer address. Do not infer an EBS callback crash
merely from missing color markers.

The new additive [diagnostic patch](ci/patch_dizi_dxecore_fb_base.py)
corrects the runtime DXE visual marker base to **`0xB8000000` only in the
disposable CI checkout**, with the original callbacks, memory-map semantics,
normal EDK2 and DarwinEnter-disabled NO-XNU policy untouched.
The separate [manual-only test workflow](.github/workflows/xnu-ebs-fb-fixed.yml)
[run #40637451443](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40637451443)
**passed 21 steps** and published a [verified separate NO-XNU boot-v4 release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-ebs-fb-fixed-40637451443-1)
with `Mu-dizi-XNU-EBS-FB-FIXED-NO-XNU.img` (68,800,512 bytes), SHA-256
`5f2752faaac66a8b94b530659b797176a9b28d0cec4848019ba5fa3cb2493f55`.
The released `DxeCore.disassembly.txt` verifies the corrected marker
instruction `movk w9, #0xb801, lsl #16` (the original was `#0xb001`).
This still requires an **on-device test**, and no XNU instruction has
been verified.
The same test also displays the first 32-bit instruction at the live EBS function pointer
at Y=276 for runtime-image fingerprinting. The previously compiled instrumented
`DxeCore.dll` begins `CoreExitBootServices` with ARM64 instruction
`0xA9BC53F3`. A mismatch on hardware indicates the runtime function is
not the identical compiled function prologue. This build has no hardware
verification yet; the exception root cause is still open.

#### EBS runtime pointer hardware observation (2026-10-28)

The **on-device** pointer diagnostic built by
[Actions #40633998662](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40633998662)
displayed **`gBS->ExitBootServices = 0x00000000FC368E3C`** in 16 framebuffer hex digits.
The same photo shows **`Synchronous Exception at 0x00000000FC368EAC`** and
the wide yellow EBS-entry marker, with no discernible thin core stripes.
The candidate load base from this pointer and the compiled RVA is
`0xFC367A08` (not 4-KiB aligned): do not claim the runtime EBS implementation
is the one in the packaged instrumented DxeCore image. 
The observed address delta **`PC - EBS = +0x70`** is valuable evidence,
but the module load base and exact source instruction are not yet proven.

The compiled **same-run** `DxeCore.map` has
`CoreExitBootServices = RVA 0x1434`, with `DiziCoreEbsMark` at
`0x169c`. In the **build output** `+0x70` corresponds to RVA `0x14a4`,
after the stage-2 marker call at `0x14a0` and before the timer shutdown
indirect call at `0x14b8`. This correspondence is **conditional on the
runtime pointer referencing the same instrumented PE image**, and does
not establish the faulting instruction or EBS callback. A screen repaint,
physical mapping or executable-image mismatch can hide old stage stripes.

A new **NO-XNU manual-only** test places 12 colored stage cells **inside**
the persistent top yellow bar and draws 12 navy calibration cells before
EBS. Its standalone
[workflow](.github/workflows/xnu-ebs-toptiles.yml) has no push trigger.
[Build #40635399461](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40635399461)
**completed successfully** (21 steps); the verified 68,800,512-byte boot-v4
is in [the NO-XNU top-tiles prerelease](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-ebs-toptiles-40635399461-1).
Boot image SHA-256: `da87e8e237ab5b3896dd516c5009cf3c6dfcec48a3deb5f59b650b2bbb555c66`.
The top-tiles image **was tested on dizi on 2026-10-28**: all 12 navy outlined
calibration cells are clearly visible inside the wide yellow band, but **none**
changed to the expected DXE stage colors; the same EBS pointer and exception PC
were observed. This proves baseline rendering works at these coordinates but
does not prove the patched CoreExitBootServices function executed. The runtime
EBS image has **not** been identified by comparing its first instruction bytes
against the compiled DxeCore.efi. A dedicated opcode fingerprint test is needed.
Neither the working EDK2 nor any EBS callbacks are
changed outside disposable CI checkout; DarwinEnter remains disabled.
Only reversible `fastboot boot` is permitted, never flashing.

#### Additional 12-stripe DXE Core trace (2026-10-28)

A second manual [DXE Core trace workflow](.github/workflows/xnu-ebs-core-trace.yml)
instruments the **pinned Mu Basecore** `CoreExitBootServices` with 12
cumulative small bands, rather than replacing the normal firmware.
It preserves all EFI event callbacks and, using the same prelinked XNU/ADT
inputs, **disables DarwinEnter** so no XNU instruction is executed.
The test is grounded in the on-device yellow-stage exception following
`ExitBootServices` in the prior probe. Source progress bands cover
BeforeExitBootServices callbacks, timer shutdown, CoreTerminateMemoryMap,
ExitBootServices callbacks, the memory-protection callback, interrupt
shutdown, and successful EBS return.

[**Verified 12-stripe image release #40630906639**](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-ebs-core-trace-40630906639-1)
contains `Mu-dizi-XNU-EBS-CORE-TRACE-NO-XNU.img` (68,800,512 bytes),
a byte-verified boot-v4 with the original checked FAT32 ramdisk.
Initial build compiled successfully, and the image was SHA-256 checked.
The publication metadata had a heredoc line-break error, corrected in
the workflow; the **original verified bytes** were then uploaded to
Releases through [publication run #40631585293](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40631585293)
without recompiling the firmware.

Only reversible `fastboot boot` is permitted. The probe may halt after
EBS; hard reboot manually. A photograph showing the **last retained
thin stripe and exception PC** is required before diagnosing or changing
individual firmware ExitBootServices callbacks. The eight-core
`sm7435-common` runtime remains untested.

### Follow-up: Yellow-only EBS boundary and DXE Core substage test

The owner ran [EBS boundary probe release #40579965947](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-ebs-boundary-40579965947-1) on hardware.
The screenshot shows a **YELLOW top bar and Synchronous Exception near
`0xFC369EAC`**; no MAGENTA. This confirms the final
`GetMemoryMap` succeeded and the exception happens *during*
`ExitBootServices` (or immediately within its own call); there is still
no XNU execution.

[**DXE Core stage probe Release #40582370738**](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-dxe-ebs-40582370738-1) was built successfully (boot-v4 image `Mu-dizi-XNU-DXE-EBS-NO-XNU.img`, 68,800,512 bytes), but **has not yet been tested on hardware**. Temporary `fastboot boot` only, never flash. Its 8 DXE color tiles are distinct from the full-width yellow loader marker.

A new manual [DxeCore substage workflow](.github/workflows/xnu-dxe-ebs.yml)
builds the *same* kernel/ADT/UEFI with 8 distinct colored tiles inserted
inside the pinned `Mu_Basecore/MdeModulePkg/Core/Dxe/DxeMain/DxeMain.c`
`CoreExitBootServices`: entry, BeforeExitBS notify completion, timer,
memory map, ExitBS notifications, memory protection, debug timer, CPU
interrupt disable. The tiles mark stages **before** each following call.
It preserves the fail-closed loader branch from the prior EBS probe,
so **no DarwinEnter/XNU execution**. A successful EBS leaves EFI and
halts; manual hard reboot required. Only temporary `fastboot boot`.


Dizi owner tested the actual XNU branch image
[release #40577187959](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-first-entry-40577187959-1)
on the physical tablet. After confirming `EXECUTE XNU`, DarwinBoot
printed the prelinked SM7435 ARM64 kernel window parameters
(`va=0xFFFFFFF00427C000`, `pa=0x80007C000`, `args=0x804188000`,
kernel physical entry `0x8031F0488`, 256 MiB owned), then
`DARWINBOOT: inputs validated; exiting boot services`.
The screen subsequently displayed `Synchronous Exception at
0x00000000FC368EAC`. **No green DarwinEnter stripe was visible.**
The exception PC is in low EFI firmware code address space rather than
the reported kernel entry region, so the leading suspicion is a fault in
the EFI final debug/GetMemoryMap/ExitBootServices path.
An ordinary EDK2 exception does NOT prove any XNU instruction executed.

The isolated [EBS boundary color probe](.github/workflows/xnu-ebs-boundary.yml)
is owner-triggered manually via `/run-dizi-ebs-boundary`. It uses
the same 51.9 MiB prelinked XNU and ADT but **NEVER invokes DarwinEnter**.
At the top of the framebuffer it paints a blue band before EFI DEBUG calls,
cyan after DEBUG calls, yellow after final successful GetMemoryMap / before
ExitBootServices, magenta if ExitBootServices returned EFI_SUCCESS, red
for an unexpected ExitBootServices error. If firmware crashes, the last
visible color can localize the crashing substage. Magenta intentionally
halts instead of calling XNU, and still requires manual hard reboot because
EFI boot services were terminated. Never `fastboot flash`.

No SMP/secondary-core inference is supported by this screenshot.

## FIRST REAL XNU entry test (2026-10-27, UNVERIFIED ON HARDWARE)

The [manual FIRST-ENTRY workflow](.github/workflows/xnu-first-entry.yml)
rebuilds the pinned, confirmed EDK2/UniXNU/DarwinBoot stack with the freshly
prelinked SM7435 + iPadOS 17.7.11 kernel candidate and reference Apple ADT.
It makes a *separate* Android boot-v4 `Mu-dizi-XNU-FIRST-ENTRY-EXPERIMENTAL.img`
rather than changing the known-good firmware. [Successful CI run #40577187959](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40577187959),
[release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-first-entry-40577187959-1).

Unlike the RAM and ADT probes, this image explicitly retains the original
DarwinBoot `ExitBootServices` and `DarwinEnter` calls, which copy kernel
segments and Apple Darwin23 `boot_args`, disable the EL1 MMU, then branch
to the physical XNU entry. Menu default is still the safe Return option.
The high-risk XNU menu action has a required Power confirmation, never
autoboots, and forces `cpus=1`.

**Danger:** XNU's memory ABI is NOT runtime-qualified, the reference ADT's
DRAM ownership is NOT validated, there is no mounted Apple OS/root/trust cache
or tested Qualcomm SMP. The image may hang, reboot, or black-screen after
`ExitBootServices` and can no longer return to UEFI. After choosing it,
a green bar at the top of the screen indicates the **loader reached the
DarwinEnter stage**, not that XNU's first instruction executed. The last
UEFI diagnostic warns that ExitBootServices is imminent. A visible XNU
log/panic after that point would be stronger evidence of real kernel code.

**Use only reversible `fastboot boot`, never `fastboot flash`.** Test only
with stable USB connection and a known hard-reboot/fastboot recovery route.
The existing UEFI and RAM-check releases remain available as fallbacks.
Before attempting the 8-core `sm7435-common` SMP/PSCI runtime changes,
obtain a reliable XNU entry or panic checkpoint and an EFI/ADT ownership
assessment.

## Prelinked XNU memory-check workflow (still NO kernel entry)

The host-side [XNU prelink workflow](.github/workflows/xnu-prelink-sm7435-linux.yml)
fetched the official Apple iPadOS 17.7.11 / 21H461 `KernelCache` member
using HTTP range ZIP access, verified the **upstream pinned original SHA-256**,
and combined its selected Apple kernel extensions with the freshly rebuilt
native SM7435 ARM64 kernel. The official `XnuPrelink` generated a 51,941,376
byte Mach-O. Its virtual segment span is about 65 MiB, within the 256 MiB
DarwinBoot window, but the prelink report says `runtime_qualified=false`
and `loadable=false`. This is not evidence of a bootable iPadOS kernel.

The manually started [prelinked UEFI memory probe](.github/workflows/xnu-prelinked-window-probe.yml)
checks the resulting Mach-O header, entry, and segment layout against DarwinBoot,
packs it with the reference ADT under `EFI/UniXNU/Payloads`, and applies a
**fail-closed DarwinBoot patch** to attempt the 256 MiB UEFI allocation and
immediately return `EFI_ABORTED`. It does not copy executable segments into
RAM, does not call `ExitBootServices`, and **never enters XNU**.

**Validated CI package (not yet tested on dizi):** [prelinked RAM-check Release #40574804304](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-prelinked-window-probe-40574804304-1) built successfully with `Mu-dizi-XNU-PRELINK-RAM-CHECK-NO-ENTRY.img` (68,800,512 bytes), checked boot-v4 ramdisk byte-for-byte, and included `PRELINK-CHECK.json` documenting the 51,941,376-byte Mach-O and that no kernel entry has occurred. This is the **first prelinked XNU boot-v4 UEFI-only probe**, not a first boot of XNU. The expected result after selecting the test entry is a temporary **`DIZI: UEFI RAM WINDOW OK / XNU NOT RUNNING`** diagnostic followed by `Aborted` and return to UniXNU, or an explicit `Out of Resources`/allocation failure if EFI cannot find a suitable window. Both outcomes require hardware validation.

For the separate source-only (no Apple binary) memory probe, the image was
successfully published in
[UEFI RAM-check release #40570339452](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-window-probe-40570339452-1).
That image has NOT been hardware-tested. Both tests must use only reversible
`fastboot boot`; **NEVER flash** these experimental images.

Only after a valid and non-overlapping device EFI allocation is demonstrated
should we construct a carefully instrumented XNU entry checkpoint. The
`sm7435-common` CPU/PSCI integration and 8-core bring-up is separate and
must follow initial XNU execution and kernel log validation.

## Experimental boot-v4 loader probe

The separate [XNU loader-probe workflow](.github/workflows/xnu-handoff-probe.yml)
is manual-only (`/run-dizi-loader-probe` from the owner on
[control PR #1](https://github.com/vildangil/UniXNU-Dizi-Ruan/pull/1),
or `workflow_dispatch`). It starts with the source-compiled
`kernel.development.dizi-UNPRELINKED.macho` verified from
[XNU source run #1](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40552223877),
and rebuilds the known dizi Mu-Silicium UEFI with an **additional pinned
DarwinBoot UEFI driver**. The hardware PMIC R4 and EFI input fixes remain in
place. This new firmware is separate from the confirmed UEFI-only release.

The loader probe copies the raw Mach-O to `Payloads/kernel.macho` inside
a 64 MiB FAT32 ramdisk and packs it in an Android boot-v4
`Mu-dizi-XNU-LOADER-PROBE-NO-PRELINK.img`. It uses the *same* 64 MiB
ramdisk size and temporary `fastboot boot` mechanism as the UEFI-only
test. The source artifact is checked against its JSON SHA-256 before use;
a mtools readback confirms the FAT copy is byte-identical to that source.

**This is a loader-protocol / payload-discovery probe, not a bootable
XNU or iPadOS release**: there is no qualified prelinked kernel,
`kernel.macho.adt`, trust cache, root filesystem or DarwinBoot-to-XNU
execution checkpoint. The new firmware must not be flashed. The probe's
XNU menu choice is opt-in and is expected to return a loader error.
Do not equate an Android boot-v4 container with a working Darwin boot
handoff. At any failure, revert to the previous UEFI-only image.

See [manual loader probe runs](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/xnu-handoff-probe.yml)
and [Releases](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases) for
actual generated files; release availability is not guaranteed until CI
finishes and the GitHub Release API succeeds.

## Building EDK2 on GitHub

Open [Actions → Dizi standalone UEFI + UniXNU (public only)](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/build.yml), choose **Run workflow**, and select **main**. No self-hosted runner or additional repository secret is required.

The workflow uses **only public** pinned [Mu-Silicium](https://github.com/vildangil/Mu-Silicium) and [upstream UniXNU](https://github.com/UniXNU/UniXNU), with no checkout, Release downloads, secrets or scripts from any experiment repository. It produces a 64 MiB FAT32 volume with safe UEFI menu actions, embeds it into an Android boot-v4 image and publishes validated outputs in [Releases](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases). Verified images are always uploaded to **Actions Artifacts** (7-day retention), even if GitHub denies publishing a Release with HTTP 403. It does not run automatically on push.

**This public-only build does not contain an XNU kernel, ADT or iPadOS.** The stock UniXNU EFI application is integrated. The latest source adds an experimental, bounded read-only FAT32 lookup in the FDT initrd after a possible LZ4 Legacy vendor ramdisk. If the FAT is absent, UniXNU displays the DXE/initrd stage instead of only `no boot entry found`. This fix has not yet been verified on the tablet; the last tested public image predates it. The image must only be tried using an already tested temporary `fastboot boot` path, never flashed to Android partitions.

### Next public-source boot test

**Source fix (2026-10-27):** The manual build workflow now applies `ci/patch_sec_entry_hob.py` (save ABL/BootShim ARM64 entry `x0` through SEC, publish the UniXNU GUID HOB) and `ci/patch_public_buttons.py` (poll already-installed EFI SimpleTextIn handles without enabling experimental PMIC/SPMI drivers). Both patch scripts existed previously, but were accidentally omitted from the standalone build workflow. The last published build, [#40364858947](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40364858947), **does not contain either patch**. A newly dispatched build is needed.

In GitHub [Actions → Dizi standalone UEFI + UniXNU](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/build.yml), dispatch `main`, and download the resulting image from the newly created run. A successful new build will include `BOOT-PATCHES.txt` in its artifact and Release. That file records the source patches included, **not** proof of working buttons or a valid DTB on hardware. The workflow is manual-only and does not run on push.

For dizi devices whose fastboot boot path was **already confirmed working**, boot the downloaded `Mu-dizi-UNIXNU-PUBLIC-UEFI-NOT-FLASHABLE.img` temporarily, without `fastboot flash`:

```cmd
fastboot devices
fastboot boot Mu-dizi-UNIXNU-PUBLIC-UEFI-NOT-FLASHABLE.img
```

Record the full red `DIZI:` status text and test Volume Up, Volume Down and Power in the menu. `no-HOB` means the argument HOB is still absent; `bad-FDT` means it exists but `x0` is not recognized as a valid DTB; `LZ4-no-FAT` means the initrd was found but the bounded FAT32 lookup failed; `FAT-published-noFS` means read-only BlockIo published and further filesystem/device registration checks are needed. Avoid reboot/erase/flash actions in any unfamiliar menu. The build has **no XNU payload** and is not an Android/XNU dualboot image.

## Assistant-triggered builds without push

The firmware workflow is intentionally **not** triggered by `push` or `pull_request`. It supports two explicit entrypoints:

- GitHub Actions → `Run workflow` (standard `workflow_dispatch`);
- a new comment containing exactly `/run-dizi-uefi` on the dedicated [manual build PR #1](https://github.com/vildangil/UniXNU-Dizi-Ruan/pull/1), authored by repository owner `vildangil`.

The second entrypoint is used so ChatGPT, via the connected GitHub app, can explicitly start a build **after code changes**, without making every push trigger CI. The job guard verifies the issue number, PR status, author and exact comment body. The workflow checks out `main` (the latest commit), not the draft PR's branch. Keep the trigger PR open and do not merge it.

Unrelated comments may create skipped workflow entries, but they cannot start a firmware build. No background workflow monitoring is implied: each launch requires an explicit comment at the time of the task.

## Clean UEFI build and experimental XNU baseline

- **Clean firmware:** [GitHub Actions #15](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40544976346), [Release](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-public-uefi-40544976346-1). Input diagnostics and raw SPMI register values are no longer drawn, while the R4 key sampler remains compiled in. This build has **no XNU kernel**. Only temporary `fastboot boot` is supported; never flash it.
- **Previous stage1 XNU:** privately built on 2026-10-21 in [run #39539783375](https://github.com/vildangil/dizi_IpadOS_maybe/actions/runs/39539783375). Archive `dizi-xnu-stage1-EXPERIMENTAL-NOT-BOOTABLE` contains `kernel.development.dizi` (ARM64 `MH_EXECUTE`, 17,223,520 bytes), `dizi.adt` (9,904 bytes), and a legacy `SWEETXNU` stage1 payload. They pass format/hash validation, **not** on-device XNU handoff.
- **New XNU compilation attempt:** manually triggered [XNU stage1 #21](https://github.com/vildangil/dizi_IpadOS_maybe/actions/runs/40544685944) on 2026-10-27; preflight failed before producing fresh kernel artifacts. A separate public CI mirror failed at `actions/checkout` because the older source repository is private. The mirror was removed to avoid depending on inaccessible private code or exposing that code in this public firmware repository.

Building a DIZI kernel is not the same as making an iPadOS-bootable firmware. UniXNU requires DarwinBoot, a valid kernel/ADT payload, verified firmware memory mappings and then an observed XNU entry point. Do not claim `kernel.development.dizi` is bootable without that work.

## Next milestones

1. Correctly expose a raw FAT32 payload to UniXNU across the LZ4/initrd handoff.
2. Load `EFI/UniXNU/unixnu.toml`, then verify XNU handoff and capture kernel logs.
3. Validate an SM7435 SoC source, firmware memory map, ADT and OS identity before enabling native builds.
4. Verify `ruan` independently.

Follow the [official device repository specification](https://unixnu.com/porting/device-repository) and [porting steps](https://unixnu.com/porting/steps). Do not flash experimental images into Android partitions.

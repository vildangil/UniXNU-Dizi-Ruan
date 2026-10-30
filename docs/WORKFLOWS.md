# GitHub Actions: Dizi / UniXNU (after consolidation)

## Active workflows

| Workflow | Purpose |
| --- | --- |
| build.yml | Manual known-good EDK2 / UniXNU firmware baseline |
| validate.yml | Static device-profile checks; also runs on relevant pull requests |
| xnu-source-sm7435.yml | Experimental compile of native XNU sources |
| xnu-prelink-sm7435.yml | Host-only XNU prelink candidate (macOS) |
| xnu-prelink-sm7435-linux.yml | Linux prelink fallback |
| publish-xnu-source.yml | Owner-approved publishing of source-build results |
| promote-dizi-control-boot.yml | Owner-controlled promotion of an existing tested image |
| xnu-mmu-ab-lab.yml | Manual B-series MMU A/B; defaults to pre-SCTLR read-only TTBR1 virtual alias slot check |

The older one-off workflow files (EBS trace, ADT, DarwinEnter, first opcode,
bootstrap checkpoints, and one-workflow-per-MMU-marker) were removed from the
active Actions menu. **No experimental scripts, git commit history, existing
Actions logs, tags, or existing Releases were deleted.** Previous workflow
files can be recovered from git history if needed.

## Build and download an XNU MMU test from GitHub

1. Go to **Actions → Dizi XNU MMU A/B diagnostic boot (manual)**.
2. Select **Run workflow**, branch **main**, and one of:
   - sixth-a: remove Y528 stack access only;
   - sixth-b: also preserve NZCV in all six MMU drawing loops;
   - orange-a: sixth-a plus a stackless ORANGE Y260 pre-SCTLR marker;
   - orange-b: sixth-b plus the same ORANGE marker (physically reached Y260 on 2026-10-29);
   - postmmu-b: historical orange-b plus Y552/Y576; the 2026-10-29 physical test was inconclusive because GOP PA may be unmapped after MMU enable;
   - text-b: original hardware-tested text console before SCTLR, no post-MMU framebuffer writes;
   - regs-b: physical screenshot confirms live pre-SCTLR EL1 register readout;
   - walk-b: hardware-proven L1/L2 block mapping for native XNU code and VBAR;
   - fbwalk-b: hardware-confirmed absence of TTBR0 identity mapping at framebuffer VA 0xB8000000 (L1=0, STATUS=1);
   - **slot-b (default, physically verified)**: L1 C0/L2 20 read-only slot probe, showing SLOT L2=0/STATUS=2 on device;
   - **alias-b (HIGH RISK, explicit opt-in; corrected after hardware MAIR guard fail)**: single guarded 2-MiB Device alias, plus post-SCTLR text checkpoints; [details and exact hash](DIZI-MMU-ALIAS-B.md);
   - guard-b: read-only historical eight-check diagnosis, hardware-confirmed `FAIL STEP 4` due to the old MAIR guard expectation.
   - **deep-b (new, manual, not hardware-tested)**: extended single-run TPIDR_EL1, return/branch into _arm_init and MPIDR CPU0 affinity checkpoints, keeping alias-b MMU method. [Detailed stages and SMP plan](DIZI-DEEP-SMP-PREFLIGHT.md).
3. Leave **publish_release=true** to replace the **one** image at
   https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-latest-test .
   With **publish_release=false** the output is only in **Actions Artifacts**.
4. Download **Mu-dizi-XNU-LATEST-TEST.img** from that Release, and verify the
   SHA-256 recorded in the Release description and MMU-AB-AUDIT.json.
5. Only ever test **temporarily** using fastboot boot; never use
   fastboot flash. Have an Android backup and working recovery method.

The original four outputs are deterministic, SHA-pinned reproductions of the verified
**fifth-NOSP Y504 base** (boot SHA-256:
b2f22f83c9b55d5a89d60f7df42488486346754911153cc502256f686681371b).
The first run creates a **separate immutable base release**
dizi-xnu-five-nosp-base so later experiments do **not** depend on the
rolling latest-test asset. The first-run fallback uses GitHub Actions run
40756904707, whose artifact expires on **2026-11-11**. If the rolling test
asset no longer matches the base and that artifact expires before the base
release is created, the workflow fails closed instead of guessing a kernel.

The workflow does **not** rebuild EDK2, does not modify Android partitions,
and has no push, pull_request, issue_comment or cron trigger. It preserves
the native TTBR1_EL1, SCTLR_EL1, and ISB instruction bytes.

## New post-SCTLR B diagnostic

After physical dizi confirmed the orange Y260 stripe using
[run #40824108833](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40824108833)
(boot SHA-256
`1c245f4da986e6ea57f928246064939ddcdc44c4833535184fa78b60532e060e`),
the `postmmu-b` experiment was added to the **same manual workflow**
and remains available as a **historical A/B option**. It rebuilds the pinned orange-b image in CI,
then applies `ci/patch_dizi_post_mmu_b.py` (only two new instrumented
Mach-O branch hooks, 88 changed bytes). Local full-image SHA-256:
`c79487a78c23db8eae9948b23dfc2f4953937dc93f89b67b2ec6bcd2a04e69af`.
It was physically tested on 2026-10-29, but Y552/Y576 were not visible. That is an **inconclusive** result, not proof of a failed SCTLR instruction.

- **Y552 cyan**: control reached the instruction *after*
  `msr SCTLR_EL1; isb` and GOP writes through the assumed V=P mapping.
- **Y576 yellow**: control also passed the native
  `cmp x0,x1; b.ne .` guard without entering its self-loop.
- If neither is visible, this is inconclusive: MMU transition, early
  exception, code cave mapping or framebuffer mapping could be at fault.
- If Y552 appears but Y576 does not, inspect the comparison and possible
  exception before claiming a register-value mismatch. Both checkpoints
  still use a physical-address framebuffer diagnostic.
- Native SCTLR, ISB, CMP, B.NE, TTBR1 and EDK2 are preserved. This is
  diagnostic code, NOT a production XNU MMU fix.

## Text-based diagnostic: text-b (historical hardware-confirmed baseline)

Source: [ci/patch_dizi_text_console_b.py](../ci/patch_dizi_text_console_b.py).
The single manual workflow reconstructs the exact pinned postmmu-b image and
then applies the new text-console patch. Expected complete Android boot-v4
SHA-256: `25842763d44144f8e35d44fa9f746e9a06ca63b4a3e08a24b8f17e8b7c9c54dc`.
Expected embedded Mach-O SHA-256:
`9c4f6f81808ccacb1607fc1ed77ff20b7e2d8079a1e5137c10bcc941b3d4cc5b`.
These exact bytes were locally reproduced from run #40915244076's image.
**The text variant reached PRE SCTLR EL1 on physical dizi** (2026-10-29 screenshot; the success message is fixed text, not measured register values).

Only two text checkpoints are active:

- `STATE: XNU ENTRY`: early Mach-O entry reached, before native CPU start.
- `NOW: PRE SCTLR EL1`: execution reached the native MOVK immediately
  preceding `msr SCTLR_EL1,x0`. The text explicitly says
  `MMU ON: NOT VERIFIED` and `POST MMU: NOT PROBED`.

The renderer paints large ASCII glyphs in a known 1600×2560 physical GOP
framebuffer while the MMU is still disabled. It clears the stale GUI/menu
and old stripe area, uses neither SP nor BootServices, and does not change
NZCV, x0/x1, or native SCTLR/ISB/guard opcodes. The previous 16 legacy
tracing branches are disabled: 14 original opcodes are restored at their
true addresses (including two PC-relative ADRP opcodes), and the Mach-O
entry plus pre-SCTLR instruction now call the text renderer. All old
trampoline bytes remain in the kernel file but are unreachable.

**No post-MMU text can be promised yet**: a verified virtual framebuffer
mapping or independently tested UART/memory-trace capture is still needed.
The removed Y552/Y576 physical-GOP probes could themselves fault after
MMU enabling and have been disabled for `text-b`. Text printed before
SCTLR means only that the preceding code ran, not that XNU booted.

The code is SHA-pinned to one kernel build, writes only to a separately
copied boot image, verifies 16 original branch sites and a completely
empty code cave in the __start padding **before** the 0xFFFFFFF0073F1000
low exception vector table, checks that compiled ARM64 instructions have no unresolved
relocations, and verifies the final complete boot-image hash.
EDK2, Android partition layout and the original native SCTLR/ISB/guard
instructions are unchanged. Test **only** with `fastboot boot` and keep a
recovery path. Do **not** `fastboot flash`.

## Register readout diagnostic: regs-b (new default, untested hardware)

The hardware-verified `text-b` boot-v4 (SHA-256
`25842763d44144f8e35d44fa9f746e9a06ca63b4a3e08a24b8f17e8b7c9c54dc`)
is reproduced **byte-for-byte** first. Then
[ci/patch_dizi_mmu_registers_b.py](../ci/patch_dizi_mmu_registers_b.py)
replaces only its existing 0x630-byte early tracing cave and the
two tracer branch sites, **without** modifying any other XNU instructions.

The new output's locally verified full boot-v4 SHA-256 is
`ccb3c22f680aa67aac58669f77c051e4784e253e7965baf3a93feb8e38374a0b`.
Mach-O SHA-256:
`a6222120639cc2fb39b5d3e353b623253d3cd9f58dd006685b95b8f1948f65eb`.
Only 1,413 Mach-O bytes change. The new ARM64 code is 1,493 bytes inside
a 1,584-byte verified cave and stops before the low exception vectors.
No extra Actions workflow, release or branch is created.

At the pre-`SCTLR_EL1` stage it uses genuine
`MRS x11,TCR_EL1`, `TTBR1_EL1`, `TTBR0_EL1`, `MAIR_EL1`,
`VBAR_EL1`, `SCTLR_EL1`, followed by copies of `x22`, `x23`,
`x25` (page-table and relocation intermediates). Values are converted
to 16 uppercase hexadecimal characters on-screen using a small
stackless ARM64 loop. The formatter writes only in its private
already-verified pre-MMU diagnostic cave; it **does not** overwrite
native Mach-O instructions. Its framebuffer drawing is the same proven
1600x2560 physical GOP renderer as `text-b` and executes **only before**
the native `SCTLR_EL1` / `ISB` sequence.

Expected headings (the hexadecimal fields below are **placeholders**;
the hardware test should replace them with actual values):

```text
DIZI / XNU MMU REGS B
NOW: PRE SCTLR EL1
TCR:       0123456789ABCDEF
TTBR1:     0123456789ABCDEF
TTBR0:     0123456789ABCDEF
MAIR:      0123456789ABCDEF
VBAR:      0123456789ABCDEF
SCTLR OLD: 0123456789ABCDEF
X22:       0123456789ABCDEF
X23:       0123456789ABCDEF
X25 TTB:   0123456789ABCDEF
MMU ON: NOT VERIFIED
POST MMU: NOT PROBED
```

- The `SCTLR OLD` value is read **before** XNU writes the new
  enable bits; a clear M bit is not an error.
- These are live register **readouts**, but they do **not** prove the
  loaded translation tables contain valid executable descriptors.
  A separate table walk / controlled hardware test is still required.
- Reading `TTBR1` / `TCR` before SCTLR can help rule out wrong
  granule, misaligned root tables, or invalid first post-ISB VA coverage.
- The tracer preserves x0/x1, x12 return handling, x18-x30, SP,
  NZCV, native SCTLR/ISB and the cmp/b.ne guard. x2-x11/x13-x17
  remain experimental scratch registers, as with the proven text-b.
- **New regs-b image has NOT been hardware-tested**. Test only using
  temporary `fastboot boot`, keep recovery working and **never flash**.
  Save a clear photo showing all hex values, the build SHA and run ID.
- This does **not** import the old ios-sweet bootloader or replace UniXNU.


**2026-10-30 hardware result:** `walk-b` reached STATUS=2, with
L1 descriptor `0x802F70003` and L2 block descriptor `0x803000601`.
The first post-ISB instruction and VBAR both translate to the exact
physical addresses predicted by x22/x23. This is evidence of a
consistent pre-MMU mapping, NOT proof of successfully enabling MMU.
A separate `fbwalk-b` test now checks whether the framebuffer
has a usable TTBR0 virtual mapping after the transition, without
accessing the framebuffer post-MMU.
See [docs/DIZI-MMU-FBMAP-B.md](DIZI-MMU-FBMAP-B.md).

## Read-only TTBR1 alias-slot B diagnostic (2026-10-31)

The physical `fbwalk-b` run (SHA-256
`e16a4c797a1afdebfe3b7bd61b47bc79a64a24c769d2c77f5a5bda4be948887b`)
showed `TTBR0=0x802F6D000`, `L1 DESC=0` and `STATUS=1`.
The low virtual address `0xB8000000` therefore has no mapping
in the observed TTBR0 root. Missing post-SCTLR physical framebuffer
writes are consistent with a translation fault, but the transition
itself is not proven to have completed.

The new `slot-b` workflow variant starts with the exact already
hardware-confirmed `walk-b` binary, modifies only **16 bytes of its
existing pre-SCTLR code cave**, and uses the same safe L1 table
probe to read L2 index `0x20` in TTBR1. This corresponds to
proposed future framebuffer alias VA `0xFFFFFFF004000000`,
separated from the current XNU code VA range. It **does not**
install the alias or write page tables.

- Output boot-v4 SHA-256:
  `ab1edbbc8b05fe9b59f0f6909ce84c75faf40c1c98edea6acb50d268c9e688ee`
- Output Mach-O SHA-256:
  `9e0f5f1411d674879ceedad09736e941349d487bb4836949e8a3bc51c4289662`
- Source: [ci/patch_dizi_mmu_slot_b.py](../ci/patch_dizi_mmu_slot_b.py).
- The text `SLOT L2: 0000000000000000` with `STATUS=2`
  means the candidate entry is unused **at the moment of this read**.
  This is not a live framebuffer mapping and not permission to
  overwrite an existing XNU table entry without further checks.
- `STATUS=0/1` means the guard or table walk did not reach L2.
  An occupied L2 entry must never be overwritten.

The test changes no EDK2, DarwinBoot, original XNU MMU system
register instructions or kernel mappings. It performs **no
post-MMU stores** and has not been tested on physical dizi yet.
Temporary `fastboot boot` only, **never flash**. Capture a clear
photo of `SLOT L2` and `STATUS` before any mapping experiment.

## Hardware-confirmed guard mismatch and one-byte correction (2026-10-31)

The physical `guard-b` display showed `FAIL STEP 4:
0C0804FF00BB44FF`, which matches the *original* `regs-b` photo.
Our previous transcription `0C0804FF008B44FF` was wrong.
This only changes MAIR **AttrIdx 2**; the alias descriptor still
selects MAIR AttrIdx 3 (`0x00` Device-nGnRnE).

Current `alias-b` changes exactly one AArch64 `MOVK` instruction
from `#0x008b` to `#0x00bb`. No MMU or native code change,
and all other safety checks remain intact. The corrected boot-v4
SHA-256 is
`ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`.
The Mach-O SHA-256 is
`991a06e89c1d75eccd0c82f7efc28127d877b8318178c343225cb3c34a341876`.
The **previous failing** alias-b SHA-256 is
`6c7f4469a9da06fbd3dc0eeafc3f04f7268ab821c8d810f1e0458b05615e044a`,
preserved in Git history and the
[hardware record](DIZI-MMU-ALIAS-B.md).

The fixed image was locally rebuilt twice with identical hashes.
It has **not** been tested on hardware. Keep `slot-b` as the
safe workflow default. `alias-b` is **explicitly selected**
because it modifies a live L2 descriptor. Only temporary
`fastboot boot`; never `fastboot flash`.

## Experimental post-MMU text via verified high VA alias (alias-b)

The physical 2026-10-31 `slot-b` photograph showed
`TTBR1 L1=0x802F70003`, `SLOT L2=0` and `STATUS=2`.
This confirms an unused L2 slot in the **pre-SCTLR** page table.
It does not establish that SCTLR enabling works.

The optional `alias-b` image changes one live descriptor
in the existing `TTBR1` L2 table **only after** verifying the
exact screenshot-derived registers, existing code mapping and
that the candidate entry is still zero. The descriptor
`0x00600000B8000C0D` maps only the first 2 MiB of the
framebuffer at `0xB8000000` into high VA
`0xFFFFFFF004000000`, with MAIR index 3 (Device-nGnRnE)
and privileged, execute-never access. It does not remap
the entire 43-MiB framebuffer and never writes via the old
unmapped TTBR0 low VA after enabling translation.

The arm64 code preserves the original SCTLR/ISB,
CMP/B.NE and native displaced instructions. If any guard
fails, the code shows `ALIAS GUARD FAIL` before MMU-on
and skips the page table write. If all checks pass and
a post-MMU text store works, the screen should show
`POST SCTLR OK`; after passing the native comparison
it should additionally show `GUARD PASSED`.
Absence of either is inconclusive.

The pinned, locally reproduced complete image SHA-256 is
`ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`.
The **corrected** variant is **not yet tested on hardware**, is
**HIGH RISK**, and is an **explicit workflow choice**,
not the default. Detailed engineering notes:
[docs/DIZI-MMU-ALIAS-B.md](DIZI-MMU-ALIAS-B.md).
As always, test only via `fastboot boot`, NEVER flash.

## Deep-b and SM7435 SMP preflight — after hardware MMU-on

The corrected `alias-b` was tested on device and displayed
`POST SCTLR OK` and `GUARD PASSED`; this **confirms native MMU-on
execution**, not an OS or secondary CPU boot. Its full SHA-256
is `ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`.

The opt-in `deep-b` test uses the same SHA-pinned `slot-b` image
and guarded high-VA framebuffer alias, adds a total of eight
native one-instruction hooks, and preserves original native
`SCTLR/ISB/CMP/B.NE`. It tracks TPIDR clearing,
return/branch from the bootstrap and the start of
`_arm_init`. The `_arm_init` marker reads the **boot core**
`MPIDR_EL1`, but does **not** start secondaries.
Only the 1,584-byte pre-vector diagnostic cave and the
eight exact hook sites can differ.

Expected new `deep-b` boot SHA-256:
`4acf22fe3b0fb389ccc057b591b7c41fc57e0e0c32eaa246342f34e85c232c45`.
Embedded Mach-O SHA-256:
`0248d8724fa4978dd2391088d82e06c9ed1130829d1d77f20229eb512a1abecd`.
The 1,543-byte ARM64 trace has no link relocations and was
rebuilt twice byte-for-byte locally. `deep-b` is not yet
hardware-tested; choose manually.

A separate offline SM7435 SMP topology check uses
`python3 ci/check_sm7435_smp.py`; a manually triggered
`validate.yml` also publishes the JSON CPU preflight artifact.
This validates eight physical Aff1 CPU IDs, a PSCI SMC
description and GICv3 resources, but not `CPU_ON` or IPI.
The SoC-only XNU reset-vector patch now preserves
`MPIDR_EL1 & 0xFFFF` unconditionally, with a pinned revision
in `feeds.toml`. The default remains `cpus=1`; a
`cpus=2` menu entry exists **only as an opt-in for a later
validated CPU1 experiment**, not as a tested runtime.

[Full diagnostic stages and SMP validation gates](DIZI-DEEP-SMP-PREFLIGHT.md).
Use temporary `fastboot boot` only, never flash.

## Interpretation / limitations

- Y480: execution reached the instrumented point before TLBI.
- Y504: execution reached the point after the TLBI/IC sequence, before VBAR.
- Y528: execution reached the point after VBAR and before SCTLR preparation.
- Y260: hardware-confirmed reaching the pre-SCTLR diagnostic marker (orange-b, 2026-10-29).
- Even all four bands are **not** proof of successful MMU enable, virtual
  memory initialization, usable userland, or iPadOS boot.
- Historical diagnostic code changes x9/x10/x11 and other temporary registers.
  The text-b painter changes x2–x11 and x13–x17 but leaves x0/x1, x12,
  x18–x30, SP and NZCV unchanged. It is still experimental instrumentation,
  not a production XNU fix.

Hardware confirmation is distinct from a successful CI build. Store a photo,
the selected variant, release SHA-256, and the exact screen result alongside
the corresponding GitHub Actions run or PR.

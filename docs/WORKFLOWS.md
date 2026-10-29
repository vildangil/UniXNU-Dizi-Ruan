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
| xnu-mmu-ab-lab.yml | Manual B-series MMU A/B; defaults to readable early-XNU text console |

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
   - **text-b (new default)**: restore original 14 old hooked instructions, replace the other two hooks with large text at Mach-O entry and immediately before SCTLR_EL1; no post-MMU framebuffer writes.
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

## Text-based diagnostic: text-b (default)

Source: [ci/patch_dizi_text_console_b.py](../ci/patch_dizi_text_console_b.py).
The single manual workflow reconstructs the exact pinned postmmu-b image and
then applies the new text-console patch. Expected complete Android boot-v4
SHA-256: `feaa33629f5830f2545b6d097e91438694029e8347badb89e243d7dda3dd4423`.
Expected embedded Mach-O SHA-256:
`5f36cafc84f1404dd1b6abc3e36f19b6def04d950f46ba2affc5c1425b956122`.
These exact bytes were locally reproduced from run #40915244076's image.
**The text variant has not been tested on physical dizi.**

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
empty code cave, checks that compiled ARM64 instructions have no unresolved
relocations, and verifies the final complete boot-image hash.
EDK2, Android partition layout and the original native SCTLR/ISB/guard
instructions are unchanged. Test **only** with `fastboot boot` and keep a
recovery path. Do **not** `fastboot flash`.

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

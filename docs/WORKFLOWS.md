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
| xnu-mmu-ab-lab.yml | **New: one manual workflow for sixth/ORANGE MMU A/B builds** |

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
   - orange-b: sixth-b plus the same ORANGE marker.
3. Leave **publish_release=true** to replace the **one** image at
   https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-latest-test .
   With **publish_release=false** the output is only in **Actions Artifacts**.
4. Download **Mu-dizi-XNU-LATEST-TEST.img** from that Release, and verify the
   SHA-256 recorded in the Release description and MMU-AB-AUDIT.json.
5. Only ever test **temporarily** using fastboot boot; never use
   fastboot flash. Have an Android backup and working recovery method.

All four outputs are deterministic, SHA-pinned reproductions of the verified
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

## Interpretation / limitations

- Y480: execution reached the instrumented point before TLBI.
- Y504: execution reached the point after the TLBI/IC sequence, before VBAR.
- Y528: execution reached the point after VBAR and before SCTLR preparation.
- Y260: would indicate reaching the pre-SCTLR diagnostic marker.
- Even all four bands are **not** proof of successful MMU enable, virtual
  memory initialization, usable userland, or iPadOS boot.
- The diagnostic code still changes x9/x10/x11 and some other pre-existing
  tracing state. These are not production XNU fixes.

Hardware confirmation is distinct from a successful CI build. Store a photo,
the selected variant, release SHA-256, and the exact screen result alongside
the corresponding GitHub Actions run or PR.

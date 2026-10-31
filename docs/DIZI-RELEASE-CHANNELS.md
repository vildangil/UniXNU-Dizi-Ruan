# Dizi release channels — owner-manual, 31 October 2026

UniXNU on Redmi Pad Pro **does not boot as a complete operating system**. "STABLE" below means an immutable, previously hardware-observed *diagnostic recovery/reference checkpoint*, not a production OS.

## Download links (same URL on both computers)

| Channel | GitHub release | Fixed asset | Purpose |
| --- | --- | --- | --- |
| STABLE reference | https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-stable | Mu-dizi-XNU-STABLE.img | Exact tested first NO-SP reference, not an OS |
| DEV BETA | https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-dev-beta | Mu-dizi-XNU-DEV-BETA.img | Latest owner-authorized experimental diagnostic |

Stable boot-v4 SHA-256: ceb970d09e05aeff9e09293528d6193a87bf760c96a6e222766df6e73e249620.
The immutable source is historic release dizi-xnu-mmu-first-nosp-40700727875-1, NOT an untested latest image.

Currently intended DEV BETA variant: fb8-readback-b, expected boot-v4 SHA-256: a0ca687c085a56460ac4307e304d6025f909ac250e4b4b9201173fde902a8335. It deliberately halts before native TTBR1 replacement and never writes an L2 entry. It has **not** been physically tested. The SHA changes when a *new* experimental build is explicitly published; always check the release notes and digest.

## Manual/owner-only controls

- **DEV BETA:** Choose main, variant fb8-readback-b, publish_release=true in the existing manual xnu-mmu-ab-lab.yml workflow, or post the exact owner command /run-dizi-fb8-readback to the open control PR #1. That exact comment always builds and publishes DEV BETA. Setting publish_release=false in manual dispatch keeps a temporary Actions artifact only (30-day retention).
- **STABLE:** Dispatch publish-dizi-stable-reference.yml manually, or post the exact owner command /publish-dizi-stable-reference on control PR #1. It verifies the old first NO-SP SHA and publishes dizi-xnu-stable **once**. It refuses to replace an existing stable release.
- DEV BETA publisher never changes STABLE or legacy dizi-xnu-latest-test. STABLE publisher never touches DEV BETA. GitHub Actions uses only workflow_dispatch and an exact owner issue_comment, not push/pull_request. validate.yml is manual-only as requested.
- Dev channels keep one .img per release and publish a SHA in the notes. Full CI build reports are attached to Actions runs.
- Any hardware test requires verified bootloader/fastboot recovery, a backup, and **temporary fastboot boot only**. NEVER fastboot flash.

## Historical release/tag retention

Eleven older GitHub Releases were present before the split. Among them, dizi-xnu-five-nosp-base is an immutable build input; dizi-xnu-mmu-first-nosp-40700727875-1 is the pinned recovery reference; dizi-xnu-source-40552223877 and the early EBS/UEFI/MMU variants document hard-won verified stages. The old dizi-xnu-latest-test tag is retained for earlier documentation links but is not updated by new MMU builds. No release is deleted solely because its title contains an old date.

The earlier one-time cleanup covered 23 *different* obsolete diagnostic tag names, archived by exact SHAs in docs/TAG_RETIREMENT_2026-10-29.md. The old cleanup code ci/cleanup_dizi_old_prereleases.sh has an explicit allowlist and protects nine historical releases. Do not run wildcard deletion or remove any release/tag needed by referenced images, pinned build inputs, or recovery.

## Current limitation

No build pass proves the physical boot, native TTBR1 switch, OS kernel VM initialization, drivers, interrupts, storage, or userland. Stable means a repeatable diagnosed reference only.

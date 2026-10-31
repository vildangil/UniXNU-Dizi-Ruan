# Dizi release channels — corrected policy (31 October 2026)

## STABLE — NOT AVAILABLE

Stable requires a **complete working UniXNU/XNU operating system** repeatedly validated on a physical Redmi Pad Pro (dizi), including native kernel VM, runtime, drivers, interrupts, storage, rootfs and userland. Successful CI, UEFI boot, XNU entry, MMU enablement or diagnostic checkpoints do NOT qualify.

The briefly published dizi-xnu-stable reference was a mistake: it duplicated the historic NO-SP entry experiment, not a functioning OS. Its duplicate release and tag are to be retired, while the original historical image remains intact.

Do not publish a Stable tag or image until a reproducible full working OS boot is documented and explicitly owner-approved. The current channel publisher refuses Stable.

## DEV BETA — experimental, may be broken

Release: https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-dev-beta
Fixed downloadable asset: Mu-dizi-XNU-DEV-BETA.img (replaced only on owner-manual publication).
FB8-READBACK-B expected SHA-256: a0ca687c085a56460ac4307e304d6025f909ac250e4b4b9201173fde902a8335. Built in GitHub Actions #41218263533; no physical execution proof. It intentionally halts and does not attempt full OS boot.

Manual/owner-only publishing: choose variant fb8-readback-b and publish_release=true in xnu-mmu-ab-lab.yml, or post the exact owner comment /run-dizi-fb8-readback on open control PR #1. publish_release=false produces only the Actions artifact. No push, pull_request or schedule triggers.

## Historical control images — NOT STABLE

- First NO-SP hardware-observed reference (SHA-256 ceb970d09e05aeff9e09293528d6193a87bf760c96a6e222766df6e73e249620): https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-mmu-first-nosp-40700727875-1
- Immutable SHA-pinned build input: https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-five-nosp-base
- Legacy rolling diagnostic release, maintained for old links: https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-latest-test

These old milestones are NOT a production OS; do not delete pinned build inputs, hardware evidence or recovery references. Earlier exact-SHA cleanup of 23 *other* obsolete tags is documented in docs/TAG_RETIREMENT_2026-10-29.md. Never delete releases by wildcard.

## Safety

Experimental images can hang, reset or damage data. Back up first, verify recovery access, only temporary fastboot boot, NEVER fastboot flash.

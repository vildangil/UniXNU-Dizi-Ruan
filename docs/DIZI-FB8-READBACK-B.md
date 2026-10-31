# Dizi FB8-READBACK-B — guarded hardware readback after FBFAIL8

**Status (2026-10-31):** built twice locally from the pinned STACK-B image; hashes, static guards and mutation checks passed. **Not yet hardware-tested.** Original FB-BRIDGE-B remains unchanged.

## Background

A real Redmi Pad Pro boot of FB-BRIDGE-B displayed FBFAIL8. Guards 1–7 therefore completed, but at least one guard-8 comparison rejected the state. Earlier LEAF-B photographs showed framebuffer L2[0x20] = 0 and code L2[0x39] = 0x0000000804193003. Those photographs do not establish the values at the later pre-switch hook.

The readback variant displays TWO actual 64-bit runtime values as 16 hex digits each:

- SLOT L2 20: new framebuffer L2[0x20] at physical 0x804192100, previously expected zero.
- CODE L2 39: new kernel-code L2[0x39] at physical 0x8041921C8, previously expected 0x0000000804193003.

The final status distinguishes FB8 SLOT BUSY, FB8 CODE DIFF, FB8 BOTH DIFF and FB8 MATCH STOP.

## Guards and scope

The ARM64 tracer preserves the bridge's first seven guards: TCR, MAIR, SCTLR.M, old TTBR1, prospective root PA/VA, L1 descriptor and the native phystokv pointer. Earlier mismatches print FBFAIL1..FBFAIL7.

This test **never writes a page-table descriptor and never performs the native TTBR1 replacement**. Even matching values halt in an intentional WFE loop. The native privileged TTBR/TLBI/DSB/ISB instructions remain unchanged. It does not prove framebuffer driver, VM completion, SMP, rootfs or userland.

The tracer is 1308 bytes in a 2032-byte code cave; only the cave, restored earlier STACK-B hook sites and one pre-switch hook change. No post-switch hook is added.

## Reproducibility pins (SHA-256)

| Image | SHA-256 |
| --- | --- |
| STACK-B input boot | 0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed |
| FB8-READBACK-B output boot | a0ca687c085a56460ac4307e304d6025f909ac250e4b4b9201173fde902a8335 |
| FB8 output Mach-O | 9b36bdd123af846f403b95d8092d78bec6dd58efcaecc42e44f4aa08a8c9f1af |
| ARM64 tracer | 6fc9dd0a5dbef6cce41c821fad4bd807da6d5763d3b1422b9b23a7fba1be5fbf |

## Manual build

Use existing workflow .github/workflows/xnu-mmu-ab-lab.yml with variant=fb8-readback-b and publish_release=false. Alternatively, an exact owner command /run-dizi-fb8-readback on the open control PR #1 launches the same workflow through issue_comment, with release publishing forcibly disabled. There is no push or pull_request trigger in the MMU workflow.

Source and negative tests: python3 ci/test_dizi_mmu_fb8_readback_b.py

**Safety:** temporary fastboot boot only, never fastboot flash. Back up the device and preserve recovery access. Photograph both hex values and status. CI success is NOT hardware validation.

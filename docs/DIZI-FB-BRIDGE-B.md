# FB-BRIDGE-B — guarded framebuffer mapping across XNU's native TTBR1 replacement

**Status (2026-10-31):** the SHA-pinned test image was locally reproduced twice from the GitHub Actions `STACK-B` artifact. Exact machine-code allowlist, two native MMU/barrier sites, payload SHA and corrupt-input refusal were checked. **GitHub Actions for this new variant and physical hardware execution are NOT yet verified.** This is a high-risk *diagnostic experiment*, not a finished framebuffer driver.

## Why the existing XNU framebuffer output disappears

Early `alias-b` proved that the diagnostic high VA framebuffer mapping `0xFFFFFFF004000000` → PA `0xB8000000` works after the **first** native `SCTLR_EL1` enable. However, `_arm_vm_init` constructs another, independent TTBR1 table hierarchy and replaces the active TTBR1. The actual `TABLE-B` and `LEAF-B` photographs measured:

| Item | Measured on the real device |
| --- | --- |
| Existing TTBR1 root before VM switch | `0x802F6E000` |
| Prospective TTBR1 root physical | `0x804191000` |
| Prospective root virtual pointer | `0xFFFFFFF008391000` |
| New L1[0xC0] table descriptor | `0x2000000804192003` |
| New L2 child physical | `0x804192000` |
| **New framebuffer L2[0x20]** | **`0x0000000000000000` (missing)** |
| New kernel code L2[0x39] | `0x0000000804193003` |
| Old framebuffer alias L2 descriptor (expected) | `0x00600000B8000C0D` |
| TCR_EL1 | `0x00000022A51A251A` |
| MAIR_EL1 | `0x0C0804FF00BB44FF` |

The new code and vector L3 PTEs were photographed as EL1-executable; stack and global pages were photographed as AP0, AF=1, private EL1 writable. These are **pre-switch table readbacks**; they do not prove successful future effective access or full VM initialization.

## What the FB-BRIDGE-B build changes

It begins from the **exact photographed `STACK-B` image** (no rebuilding EDK2, no changes to Android partitions). It removes the old four STACK-B VM tracer hooks, then uses two separate one-opcode hooks:

1. **Pre-switch `0xFFFFFFF0073EA0B0`**: after the native `qsort` and *before* physmap metadata is replaced. It checks the observed TCR, MAIR, current TTBR1, new table identity and verified framebuffer descriptor. It calls the existing native `_phystokv` **only for known and pinned old/new L2 page physical addresses** and refuses a returned pointer that differs from the observed canonical mapped VA. It checks new L2[0x20] is zero and new code L2[0x39] is unchanged. Only if all checks succeed, it writes the **single exact old Device L2 block descriptor** into new L2[0x20], issues `DSB ISHST`, reads back the entry and prints `FB ALIAS READY`. It then returns to the original native `ADRP x8` and normal XNU code.
2. **Post-switch `0xFFFFFFF0073EA130`**: immediately AFTER the original XNU TTBR1/TTBR0 helper calls at `0x...EA10C/EA120` and native `TLBI VMALLE1IS; DSB ISH; ISB` at `0x...EA124..EA12C`. It reads TTBR1_EL1 and SCTLR_EL1.M. If the root is the expected `0x804191000` and MMU remains enabled, it prints **`FB NEW TTBR OK`** via the newly installed high VA framebuffer alias and returns to the original `ADRP x8` instruction.

The original native `TTBR`, `TLBI`, `DSB`, `ISB`, `SCTLR` and comparison instructions are not changed. No PSCI, CPU_ON, GIC MMIO or storage writes are added. The output remains in the first **2 MiB** of the reserved 43-MiB splash region (1600×2560, 6400-byte stride). This is NOT a mapping of the entire display or a userland framebuffer driver.

## Read the screen

| Result | Interpretation |
| --- | --- |
| `FB ALIAS READY` only | The new L2 slot was populated and read back. **Not proof** the subsequent native TTBR switch happened. The CPU may have stopped later or lost framebuffer/code mapping. |
| `FB NEW TTBR OK` | The CPU reached the *post-ISB hook*, read the expected new TTBR1 and displayed through the high VA alias. This confirms post-switch framebuffer access at that point, **not** completion of `_arm_vm_init`. |
| `FBFAIL1` | TCR differs. |
| `FBFAIL2` | MAIR differs. Do not “correct” by changing the memory type blindly. |
| `FBFAIL3` | SCTLR.M was zero. |
| `FBFAIL4` | The active old TTBR1 root differs. |
| `FBFAIL5` | The new root physical and/or native virtual identity differs. |
| `FBFAIL6` | The new L1[0xC0] descriptor differs. |
| `FBFAIL7` | Native `phystokv` did not return the exact expected new L2 VA. |
| `FBFAIL8` | New framebuffer slot is already occupied or the code L2 descriptor changed. |
| `FBFAIL9` | Old live framebuffer descriptor/pointer differs, or the new descriptor readback failed. |

**Fail-closed behavior:** On any pre-switch guard failure, it prints `FBFAILn` using the **existing** mapped alias and deliberately enters a low-power `WFE` loop **before** the native TTBR switch. An intentional refusal is not an XNU kernel panic. After the switch, an unexpected TTBR1 or disabled MMU similarly avoids touching the unverified framebuffer and stops without a new text line. A blank screen cannot isolate the fault.

**Risk:** the experiment changes one live *future* page-table descriptor and may fault, hang or perturb XNU's own VM assumptions. Exact addresses and descriptors are pinned to one measured hardware configuration, and may legitimately differ on a later boot. The previous `stack-b` read-only image remains available for rollback. Only temporary `fastboot boot`, **NEVER `fastboot flash`**. Keep recovery accessible.

## Additional source-only preflight (added during continuation)

The existing `fb-bridge-b` manual Actions selection now runs
[`ci/check_dizi_fb_bridge_contract.py`](../ci/check_dizi_fb_bridge_contract.py)
**before** building the new image. The existing manual/PR
`validate.yml` also runs the same source-only checker and uploads
`dizi-fb-bridge-precheck.json`. The main builder stores an additional
`dist/FB-BRIDGE-PRECHECK.json` in its image/audit artifact.

This is deliberately independent of the binary SHA checks:

- It requires the photographed TCR/TTBR1 4KiB/38-bit/40-bit geometry,
  new `L1[C0]/L2[20]` slot absent, code-vector L3 pages mapped
  executable to the reference PAs, and active stack/global pages
  EL1 writable to the corresponding bootstrap PAs.
- It decodes `0x00600000B8000C0D`: 2-MiB block at
  `0xB8000000`, AttrIdx3 with `MAIR[31:24]=0x00`
  Device-nGnRnE, AF1, nG, EL1 RW, UXN1 and PXN1.
  It checks that the mapped 2 MiB lies inside the observed
  43-MiB splash framebuffer reservation.
- It independently audits the source: guards precede the **single**
  `STR X5,[X19,#0x100]`, `DSB ISHST` precedes readback,
  two refusal loops remain, and post-switch rendering only follows
  TTBR1 and SCTLR.M checks. The original ADRP replay remains
  required; no PSCI `CPU_ON` is permitted.
- Four negative cases must refuse an occupied alias slot, a
  non-writable stack PTE, the missing descriptor store and a
  missing DSB barrier.

The audit source was committed to `main`; a separate JS inspection
of current GitHub source and snapshot data passed. **A new GitHub
Actions run has not yet executed this Python preflight**. If the
preflight fails, fix or explain the mismatch before a physical test;
do not disable guards merely to produce an image.

These are strictly pre-switch source/hardware-data consistency
checks. They do **not** independently compare current old-root
stack contents, prove post-TLBI access, prove writable physical GOP
for an XNU driver, or confirm the switch itself.

## Reproducibility

| Binary | SHA-256 |
| --- | --- |
| Input, physical `STACK-B` boot-v4 | `0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed` |
| Input `STACK-B` Mach-O | `396b1c94f6024efbd534957ea9fc6708ab1178997d2ae7fcf6ba61d3afc59f3d` |
| **Output `fb-bridge-b` boot-v4** | **`4ff3a8f6839bc3ba9f33a91356b9f55e4e8cd65d6fafaf30391ba41e5babd195`** |
| Output Mach-O | `4ea7271ea3aefcd741dab55fff5f2f4bbfbec0252c38176da1038ca9cd3f2c3c` |
| Source-generated ARM64 tracer | `1ad661288c843dab1bb6f5f1aa9567763da9d5aad1c8bf7801c359b391793379` |

The observed `STACK-B` input was downloaded from GitHub Actions artifact `13043368686`, verified as **68,800,512 bytes** with the exact expected SHA. In the new output, the tracer is **1,463 of 2,032 available code cave bytes** at `0xFFFFFFF0073F1800`; only 1,667 Mach-O bytes change, confined to this cave and five four-byte branch/original-site locations. The original four STACK-B hook sites are restored where not reused. The source contains exactly **one** native `STR X5,[X19,#0x100]` write to the future framebuffer L2 entry.

Reproduce (from the existing pin-verified `STACK-B` image):

```sh
python3 ci/patch_dizi_mmu_fb_bridge_b.py \
  --input /tmp/Mu-dizi-XNU-STACK-B-HIGH-RISK.img \
  --output /tmp/Mu-dizi-XNU-FB-BRIDGE-B-HIGH-RISK.img \
  --report /tmp/FB-BRIDGE-AUDIT.json
python3 ci/test_dizi_mmu_fb_bridge_b.py \
  --input /tmp/Mu-dizi-XNU-STACK-B-HIGH-RISK.img \
  --output /tmp/Mu-dizi-XNU-FB-BRIDGE-B-HIGH-RISK.img
sha256sum /tmp/Mu-dizi-XNU-FB-BRIDGE-B-HIGH-RISK.img
```

Two local independent executions produced byte-identical output. Host tests verify input corruption refusal, payload integrity, original privileged MMU/TTBR instructions, branch hooks, allowed modified regions and unique L2 store; **they do not emulate hardware MMU translations**. The existing manual workflow now offers `fb-bridge-b` as explicit opt-in, retains safe `slot-b` default, and reconstructs the full pinned `stack-b` chain before building it. **Do not claim GitHub Actions or hardware success until separately checked.**

## Next goal

If `FB NEW TTBR OK` is physically observed, preserve the bridge while tracing the rest of `_arm_vm_init` and its return, then review proper native XNU pmap/IO-memory registration instead of leaving an ad-hoc descriptor in the early page table. If a numbered guard fails, record the first failing condition and fix the underlying ownership/translation issue; do not skip the guard.

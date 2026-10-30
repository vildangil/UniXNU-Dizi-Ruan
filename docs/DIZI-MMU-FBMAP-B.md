# Dizi: hardware-confirmed XNU L1/L2 map and next TTBR0 framebuffer check

## Screenshot from 2026-10-30 — walk-b

The device reached the pre-SCTLR page-table walker and printed:

| Field | Observed value |
| --- | --- |
| TCR_EL1 | `0x00000022A51A251A` |
| TTBR1_EL1 | `0x0000000802F6E000` |
| VBAR_EL1 | `0xFFFFFFF0073ED000` |
| L1 descriptor | `0x0000000802F70003` |
| L2 descriptor | `0x0000000803000601` |
| L3 PC / L3 VBR | both zero |
| STATUS | 2 |
| x22 | `0xFFFFFFF007004000` |
| x23 | `0x0000000802E04000` |

`STATUS=2` is expected: the L2 descriptor is a valid **2-MiB block**,
not a pointer to an L3 table. Its output physical base is
`0x803000000`, with Access Flag set and privileged execute-never clear.
`TCR.T1SZ=26` permits 38-bit TTBR1 VA; consequently the **L1 root
index is C0**, not 1C0. The L2 index is 39. Its table is at
`0x802F70000`, obtained from the L1 descriptor.

The first post-ISB instruction VA `0xFFFFFFF0073F2358` translates to
PA `0x8031F2358`. VBAR VA `0xFFFFFFF0073ED000` translates
to PA `0x8031ED000`. Both exactly match the independent
`x23 + (VA - x22)` kernel relocation calculation.

Reproduction (no device access necessary):

```sh
python3 ci/check_dizi_walk_b_translation.py \
  --input data/dizi-walk-b-hardware-20261030.json
```

This establishes *consistent pre-SCTLR descriptor contents* for these
two addresses, **not** that execution crossed the MMU transition. Other
VA ranges, memory attributes, exception-vector code and live post-MMU
behaviour remain unverified.

## fbwalk-b — next read-only pre-MMU test

To determine why the old physical-address GOP stores did not work
after enabling MMU, the next test should inspect TTBR0's translation
of virtual address `0xB8000000`, the observed physical framebuffer
address. The currently measured TTBR0 root PA is `0x802F6D000`.

The new `fbwalk-b` variant uses the **same** single manual MMU workflow
and rebuilds the exact `walk-b` base; it modifies only **40 bytes**
inside the already existing diagnostic cave. No other XNU instructions,
EDK2 or working firmware are modified. It checks the measured TCR,
TTBR0 and VBAR values before reading an entry.

Expected lookup: TTBR0 **L1 index 02** and, if L1 is a table,
**L2 index 1C0**. If L1 is a valid 1-GiB block, the walker may stop
at `STATUS=1` with no L2 descriptor. If L2 is a 2-MiB block it
will stop at `STATUS=2`, with zero L3 fields; if L2 points to a
table it attempts L3 indices 0 and 1 and may reach `STATUS=3`.

Do **not** infer a successful framebuffer virtual mapping merely
from a nonzero descriptor; attributes, identity output address,
range coverage and the translation regime must be checked.

- `walk-b` input SHA-256:
  `8c5c1aba446897a7548461a05718d79ddfb5607cfd0745c5187d423ed3a05542`
- `fbwalk-b` locally verified Android boot-v4 SHA-256:
  `e16a4c797a1afdebfe3b7bd61b47bc79a64a24c769d2c77f5a5bda4be948887b`
- `fbwalk-b` embedded Mach-O SHA-256:
  `bee3a4d609965fc0a65423ff5080fdcaa0a8e9fa70f134517ebc9327d630d426`
- Script: `ci/patch_dizi_mmu_fbwalk_b.py`.

The image remains **untested on hardware**. It does not add post-MMU
framebuffer writes; its sole task is to inspect translation descriptors.
Any further post-SCTLR console changes must wait for these results.

Tests are strictly **temporary `fastboot boot` only**, never
`fastboot flash`. No new branch or new workflow is necessary.

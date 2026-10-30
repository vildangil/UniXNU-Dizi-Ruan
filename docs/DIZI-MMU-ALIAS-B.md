# Dizi UniXNU: guarded MMU-on framebuffer alias B

## First confirmed XNU MMU-on execution on dizi (31 October 2026)

A physical tablet screenshot of **corrected `alias-b`** shows, in order:

```text
DIZI XNU ENTRY
PRE ALIAS ARMED
POST SCTLR OK
GUARD PASSED
```

The rolling GitHub release at hardware-test time contained exactly
`Mu-dizi-XNU-LATEST-TEST.img`, SHA-256
`ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`,
published by [Actions run #41136028600](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41136028600).
The photographed messages match the SHA-pinned ARM64 code.

**Hardware-confirmed facts:** a single TTBR1 L2 framebuffer alias was
installed after guarded checks, the CPU executed the native
`msr SCTLR_EL1, x0` and `isb` and reached the next hook, `SCTLR.M`
read back as enabled, and the renderer wrote through the TTBR1
**high virtual address** `0xFFFFFFF004000000`. The CPU also
passed the untouched native `cmp x0,x1; b.ne .` check and reached
the `0xFFFFFFF0073F2370` hook.

**Not yet confirmed:** execution of the subsequent native
`msr CPACR_EL1, x0` at `0xFFFFFFF0073F2374`,
`msr TPIDR_EL1, xzr` at `0xFFFFFFF0073F2378`,
return/branch at `0xFFFFFFF0073F2388/239C`, higher XNU
bootstrap routines, IOKit, rootfs or userland. The underlying
UniXNU EDK2 screen remains visible because the diagnostic clears
only the first 2 MiB of the framebuffer; it does not mean EDK2
resumed executing.

The observation is preserved as structured data in
[`data/dizi-alias-b-mmu-on-hardware-20261031.json`](../data/dizi-alias-b-mmu-on-hardware-20261031.json).
**Keep the tested corrected alias-b SHA as a hardware-proven
checkpoint**, not a full OS boot claim.

## Historical initial alias-b failed MAIR guard (2026-10-31)

The physical dizi screenshot of the exact `alias-b` Release
(SHA-256 `6c7f4469a9da06fbd3dc0eeafc3f04f7268ab821c8d810f1e0458b05615e044a`)
shows **DIZI XNU ENTRY** and **ALIAS GUARD FAIL**.
The previous UniXNU menu remains visible beneath the diagnostic region
because this renderer clears only the first 2 MiB of the framebuffer;
that is not evidence the EFI menu was entered again.

The fail branch occurs **before** the alias page-table store, so this
photo does not demonstrate the installation of a framebuffer mapping or
successful MMU enable. No `POST SCTLR OK` or `GUARD PASSED`
checkpoint was reported. The later hardware-tested `guard-b`
identified **FAIL STEP 4**, showing actual
`MAIR_EL1=0x0C0804FF00BB44FF`. The original guard expected
`0x0C0804FF008B44FF` due to a mistaken photo transcription.
This was an instrumentation error, not evidence of a hardware MAIR fault.

### Safer diagnostic: guard-b (hardware-confirmed failure at step 4)

New source in main:
[`ci/dizi_mmu_guard_b.S.in`](../ci/dizi_mmu_guard_b.S.in)
and [`ci/patch_dizi_mmu_guard_b.py`](../ci/patch_dizi_mmu_guard_b.py).
They reconstruct the exact hardware-tested `slot-b` image, use the
same early framebuffer font, check all eight alias preconditions,
and display either `ALL CHECKS PASS` or
`FAIL STEP N: <16-digit actual hexadecimal value>`.

| Step | What was measured |
| --- | --- |
| 1 | TCR_EL1 |
| 2 | TTBR1_EL1 |
| 3 | VBAR_EL1 |
| 4 | MAIR_EL1 |
| 5 | SCTLR_EL1 M bit (must be disabled before transition) |
| 6 | TTBR1 L1 kernel table descriptor |
| 7 | TTBR1 L2 executable kernel block descriptor |
| 8 | Proposed alias L2 entry (must be zero) |

The measured actual register/descriptor is printed for the first
disagreement, without attempting to bypass any safety guard.
No page-table descriptors are written. No post-MMU framebuffer writes
are added. Original native SCTLR/ISB/CMP/B.NE remain unchanged.

Pinned output boot-v4 SHA-256:
`17e9504f4737d4b483df5c9d4fbd85d07a5829fd6fe3d711b9f0a3530ac8fba3`.
Pinned output Mach-O SHA-256:
`7fc9719c6d5205a911be58244e5242c55c3b6821bb4ec2756ff70b2a2ec69b6f`.
Locally rebuilt twice with identical SHA, and hardware-tested on dizi:
`DIZI XNU ENTRY / FAIL STEP 4: 0C0804FF00BB44FF`.
The existing manual [MMU A/B workflow](../.github/workflows/xnu-mmu-ab-lab.yml)
includes **guard-b** for reproducing the now-understood failure.
The safer default is **slot-b**; the fixed, high-risk `alias-b`
must be chosen explicitly. All historical diagnostic variants remain
available. Use temporary `fastboot boot` only; never flash partitions.

## Fixed `alias-b` (2026-10-31): one-byte MAIR guard correction

The photo in the previous section and the original `regs-b` photo
both read **`0x0C0804FF00BB44FF`**. The old `alias-b` expected
`0x0C0804FF008B44FF`: it rejected a healthy register because
the previous photograph had been transcribed incorrectly.
These values differ in **MAIR AttrIdx 2**; the actual framebuffer
mapping uses **AttrIdx 3**, which remains `0x00` and means
Device-nGnRnE. No change in the memory type is needed.

Corrected the single AArch64 immediate
`movk x10, #0x008b, lsl #16` to
`movk x10, #0x00bb, lsl #16` in
[`ci/dizi_mmu_alias_b.S.in`](../ci/dizi_mmu_alias_b.S.in).
The rebuilt image differs from the previously published failing
`alias-b` in **exactly one byte**, inside the existing experimental
diagnostic code cave. All other bytes, including native
`SCTLR_EL1/ISB/CMP/B.NE`, the framebuffer descriptor,
EDK2, and Android boot metadata, are unchanged.

| Image | Full boot-v4 SHA-256 |
| --- | --- |
| Historical failed alias-b | `6c7f4469a9da06fbd3dc0eeafc3f04f7268ab821c8d810f1e0458b05615e044a` |
| **Corrected current alias-b** | **`ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`** |

Corrected embedded Mach-O SHA-256:
`991a06e89c1d75eccd0c82f7efc28127d877b8318178c343225cb3c34a341876`.
The fixed image was rebuilt twice locally with identical hashes and
the original and corrected images were compared byte-by-byte.
**The corrected alias-b has since been tested on physical hardware and passed both post-SCTLR text checkpoints (see the new hardware result above).**

This still **writes one live L2 descriptor** after exact guards.
It can fault or hang; it is NOT a confirmed MMU fix.
Only explicit opt-in `alias-b`, temporary `fastboot boot`,
a working recovery, and **NEVER `fastboot flash`**.
Look for `PRE ALIAS ARMED`, `POST SCTLR OK`,
`GUARD PASSED` or `ALIAS GUARD FAIL`. Absence of
post-MMU text is inconclusive.

## Hardware basis, 31 October 2026

The user's on-device **slot-b** screenshot reached the existing
pre-`SCTLR_EL1` tracing hook, showing:

| Field | Measured |
| --- | --- |
| `TCR_EL1` | `0x00000022A51A251A` |
| `TTBR1_EL1` | `0x0000000802F6E000` |
| `VBAR_EL1` | `0xFFFFFFF0073ED000` |
| `L1 DESC` | `0x0000000802F70003` |
| `SLOT L2` | **`0x0000000000000000`** |
| `STATUS` | **2** |

This proves the prospective **TTBR1 L1 C0 / L2 20** descriptor was
unused at that instant. Earlier `walk-b` independently confirmed
that the existing native kernel code and exception vectors were
covered by an L2 block, `0x0000000803000601`, at index 39.
Earlier `fbwalk-b` confirmed the low framebuffer address
`0xB8000000` was **not** mapped by the existing `TTBR0` table
(L1 descriptor 0). These are pre-MMU hardware measurements; they do
not prove that the CPU has already executed any post-SCTLR opcode.

The exact photographed image is archived as
[`data/dizi-slot-b-hardware-20261031.json`](../data/dizi-slot-b-hardware-20261031.json).
SHA-256 of the working `slot-b` boot-v4 is
`ab1edbbc8b05fe9b59f0f6909ce84c75faf40c1c98edea6acb50d268c9e688ee`.

## New experimental option: `alias-b`

The sole manual workflow
[`xnu-mmu-ab-lab.yml`](../.github/workflows/xnu-mmu-ab-lab.yml)
now includes **alias-b** as an *explicit choice*. The default
stays `slot-b` because this next experiment **modifies a live
XNU page-table entry**. It is intentionally opt-in and **HIGH RISK**.

The option rebuilds the SHA-pinned, hardware-tested `slot-b` image
and uses [`ci/patch_dizi_mmu_alias_b.py`](../ci/patch_dizi_mmu_alias_b.py)
and the independently auditable
[`ci/dizi_mmu_alias_b.S.in`](../ci/dizi_mmu_alias_b.S.in)
to replace only the existing pre-vector diagnostics area and
two post-SCTLR single-instruction hooks. It does **not** replace
UniXNU, DarwinBoot, EDK2, the Android boot header, or normal kernel code.

Before writing the new descriptor, the native pre-SCTLR handler
checks exact *live* register values against the photographed
`TCR_EL1`, `TTBR1_EL1`, `VBAR_EL1` and `MAIR_EL1`,
verifies the old `SCTLR.M=0`, checks the existing
`L1=0x802F70003` and executable kernel `L2=0x803000601`,
and rechecks that alias slot `L2:20` is still zero.
On a mismatch, it prints **ALIAS GUARD FAIL**, makes **no
page-table changes**, and skips both post-MMU framebuffer writes.

On an exact match, it installs **one** 2-MiB TTBR1 block:

| Field | Value |
| --- | --- |
| High virtual framebuffer alias | `0xFFFFFFF004000000` |
| Physical framebuffer base | `0xB8000000` |
| L2 entry physical address | `0x802F70100` |
| New 64-bit L2 descriptor | `0x00600000B8000C0D` |
| Memory type | MAIR index 3 = `0x00`, Device-nGnRnE |
| Access | EL1 read/write, Access Flag set, non-global |
| Execution | Privileged and unprivileged execute-never |
| Coverage | First 2 MiB of the 43-MiB reserved framebuffer |

After the store, it executes `DSB ISHST`, `TLBI VMALLE1`,
`DSB ISH`, `ISB`, then returns to the **original**
`msr SCTLR_EL1,x0` / `isb`. The original native
`cmp x0,x1; b.ne .` is also unchanged. Post-MMU
instrumentation uses the **high VA alias only**, never the
unmapped low `0xB8000000` address. A small stackless 5×7
font prints exclusively inside the first 2-MiB block.

Expected visible stages, in order:

```text
DIZI XNU ENTRY
PRE ALIAS ARMED
POST SCTLR OK
GUARD PASSED
```

- `PRE ALIAS ARMED`: checks passed and the block descriptor
  was written; **no** successful MMU switch is proven.
- `ALIAS GUARD FAIL`: one or more checks disagreed with the
  screenshot; there should be **no** alias installation.
- `POST SCTLR OK`: the CPU fetched instructions after native
  `SCTLR_EL1; ISB`, confirmed `SCTLR.M=1`, and reached
  a working post-MMU store through the new high VA alias.
- `GUARD PASSED`: execution passed the original `cmp/b.ne`
  self-loop and completed the second text checkpoint.

If no post-MMU text appears, this **does not prove** the
SCTLR instruction itself failed. A translation, cache, display,
attribute or exception fault remains possible. A visible
post-MMU message would prove only this checkpoint, **not** full XNU
or iPadOS boot. This single alias is a temporary diagnostic and
must not be retained as a general framebuffer-driver implementation.

## Reproducibility and safety

- Input boot SHA-256:
  `ab1edbbc8b05fe9b59f0f6909ce84c75faf40c1c98edea6acb50d268c9e688ee`
- Locally reproduced output boot SHA-256:
  `ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`
- Output embedded Mach-O SHA-256:
  `991a06e89c1d75eccd0c82f7efc28127d877b8318178c343225cb3c34a341876`
- Compiler: clang AArch64 assembler, `llvm-objcopy`, `readelf`,
  `nm`; the compiled trace has no unresolved relocations.
- Trace size: 1,163 bytes out of a pre-verified 1,584-byte cave.
- Original native `SCTLR_EL1`, `ISB`, `CMP`, `B.NE`,
  EDK2, and the other boot-image bytes are unchanged.

**This image has now been run successfully through the post-SCTLR and native compare checkpoints on dizi; later boot stages are not confirmed.** The new entry
may change the behaviour of the native bootstrap, and faulty mappings
may produce a black screen, an exception, or a hang. Have working
fastboot/recovery access and backups. **Use only `fastboot boot`;
never `fastboot flash` or overwrite Android partitions.**

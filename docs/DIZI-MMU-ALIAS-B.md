# Dizi UniXNU: guarded MMU-on framebuffer alias B

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
  `6c7f4469a9da06fbd3dc0eeafc3f04f7268ab821c8d810f1e0458b05615e044a`
- Output embedded Mach-O SHA-256:
  `fc51ca317cadc189042a78658f742ad78e9ea0af6bad60fead5dd1425db582f1`
- Compiler: clang AArch64 assembler, `llvm-objcopy`, `readelf`,
  `nm`; the compiled trace has no unresolved relocations.
- Trace size: 1,163 bytes out of a pre-verified 1,584-byte cave.
- Original native `SCTLR_EL1`, `ISB`, `CMP`, `B.NE`,
  EDK2, and the other boot-image bytes are unchanged.

**This image has never been run on dizi hardware.** The new entry
may change the behaviour of the native bootstrap, and faulty mappings
may produce a black screen, an exception, or a hang. Have working
fastboot/recovery access and backups. **Use only `fastboot boot`;
never `fastboot flash` or overwrite Android partitions.**

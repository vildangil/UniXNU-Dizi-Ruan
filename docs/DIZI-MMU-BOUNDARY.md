# Dizi / XNU MMU handoff: observed text-b (2026-10-29)

## Hardware evidence
The user tested `text-b` from GitHub Actions run #40930881144.
Release boot-v4 SHA-256: `25842763d44144f8e35d44fa9f746e9a06ca63b4a3e08a24b8f17e8b7c9c54dc`.
Embedded Mach-O SHA-256: `9c4f6f81808ccacb1607fc1ed77ff20b7e2d8079a1e5137c10bcc941b3d4cc5b`.
The on-device photograph displays:

```text
DIZI / XNU DEBUG
PASS: XNU ENTRY
PASS: BOOTARGS / TTB
PASS: TTBR1 MAIR TLBI VBAR
NOW: PRE SCTLR EL1
MMU ON: NOT VERIFIED
POST MMU: NOT PROBED
```

This confirms that the text renderer reached the pre-SCTLR instruction hook.
The PASS labels are precompiled strings, not independent hardware register reads.
MMU-on, exception handling, further native execution, and userland remain unconfirmed.

## Exact pinned Mach-O disassembly around MMU enable

| Address | Native instruction |
| --- | --- |
| `0xFFFFFFF0073F22B8` | `msr TTBR1_EL1, x0` |
| `0xFFFFFFF0073F2300` | `msr MAIR_EL1, x0` |
| `0xFFFFFFF0073F2308` | `tlbi vmalle1` |
| `0xFFFFFFF0073F233C` | `msr VBAR_EL1, x0` |
| `0xFFFFFFF0073F234C` | branch to stackless text-b trampoline, replays `movk x0,#0x593d` |
| `0xFFFFFFF0073F2350` | `msr SCTLR_EL1, x0` |
| `0xFFFFFFF0073F2354` | `isb` |
| `0xFFFFFFF0073F2368` | `cmp x0, x1` |
| `0xFFFFFFF0073F236C` | `b.ne .` (self-loop on mismatch) |
| `0xFFFFFFF0073F2370` | `mov x0, #0x300000` |

The static code assembles x0 and x1 as `0x3454593d` before comparison; this
is NOT a measurement of the runtime register values. The bootstrap also
builds 2-MiB mapping descriptors using boot-time relocation offsets.

## Current failure boundaries

- Absence of former post-MMU Y552/Y576 stripes was inconclusive because they
  wrote directly to framebuffer physical address 0xB8000000; once translation
  is enabled, this PA is not a verified valid VA.
- There is no post-MMU output in text-b, by design. A stale final status line
  is not proof that `SCTLR_EL1` itself failed.
- The device's runtime DRAM ownership / carveouts, TTBR1 physical tables,
  TCR stage-1 configuration, framebuffer alias and VBAR mapping remain unverified.
- `board.toml` is still `example=true`; native XNU runtime is not qualified.

## New recovery-based memory evidence (2026-10-29)

The physical tablet's root-capable recovery yielded a full 851,838-byte
FDT v17, matching sysfs Device Tree tarball, `/proc/iomem`, full dmesg,
cmdline and meminfo. Detailed, sanitized findings:
[docs/DIZI-RECOVERY-MEMORY-20261029.md](DIZI-RECOVERY-MEMORY-20261029.md).

Critical data:
- `/reserved-memory/splash_region`: PA `0xB8000000`, 43 MiB.
  Valid *physical* reserve only, not proof of a post-SCTLR virtual alias.
- `ramoops`: `0x80D00000` + 2 MiB.
- A previous proposed 1 GiB XNU RAM candidate at `0x8C0000000`
  contains Linux recovery reserved allocations beginning at
  `0x8F6B00000`. It is therefore **not** an approved 1 GiB runtime pool.
  Even subranges without `/proc/iomem` reservations cannot be
  considered free in EDK2 until its *own* current memory map is obtained.
- Recovery `/chosen/stdout-path` points to UART `0x98C000`,
  but Linux reported **Console Disabled**. Do not assume a working
  serial post-MMU channel.

The recovery data allow us to rule out unsafe allocations, but do not
read XNU's runtime TTBR1, TCR, VBAR or page-table contents. The next
test should capture those values **before** SCTLR using the existing
UniXNU design, with firmware-owned allocations verified.

## New measured EL1 register snapshot (2026-10-30, regs-b)

The user tested the SHA-pinned `regs-b` binary (boot SHA-256
`ccb3c22f680aa67aac58669f77c051e4784e253e7965baf3a93feb8e38374a0b`).
The on-device photograph shows actual `MRS` readings just before the
native `msr SCTLR_EL1, x0`:

| Value | Observed at pre-SCTLR |
| --- | --- |
| TCR_EL1 | `0x00000022A51A251A` |
| TTBR1_EL1 | `0x0000000802F6E000` |
| TTBR0_EL1 | `0x0000000802F6D000` |
| MAIR_EL1 | **`0x0C0804FF00BB44FF`** |
| VBAR_EL1 | **`0xFFFFFFF0073ED000`** |
| SCTLR_EL1 (old, before write) | `0x0000000030D00808` |
| x22 | `0xFFFFFFF007004000` |
| x23 | `0x0000000802E04000` |
| x25 | `0x0000000802F6D000` |

**31 October 2026 correction:** The actual `regs-b` photo and independent
`guard-b` run both show `MAIR_EL1=0x0C0804FF00BB44FF`.
The previously transcribed `0x0C0804FF008B44FF` was a visual
error (`BB` mistaken for `8B`), not a runtime MAIR register change.
The discrepancy is in MAIR **AttrIdx 2**; AttrIdx 3 remains `0x00`
(Device-nGnRnE), used by the optional framebuffer alias experiment.

**Corrected visual transcription:** VBAR ends in `3ED000`, not
`3E0000`; the enlarged original photo and the source `ADRP`
at `0xFFFFFFF0073F232C` agree.

TCR's `T1SZ=26` means a 38-bit TTBR1 VA range, `TG1=2`
means 4KiB pages, and `IPS=2` allows 40-bit physical addresses.
`TTBR1=0x802F6E000` is 4KiB-aligned and in recovery-observed RAM.
This is a **plausible** setup, not a validated page table.

First post-ISB kernel PC `0xFFFFFFF0073F2358` and
`VBAR=0xFFFFFFF0073ED000` share the same L1 index `0xC0`
and L2 index `0x39` for 4KiB granule / 38-bit VA. A bounded,
read-only page-table diagnostic can therefore inspect:
`*(uint64_t *)(0x802F6E000+0x600)` (L1), the resulting L2
table's entry `+0x1C8`, and (if L2 selects L3) PC index
`0x1F2` at `+0xF90` and VBAR index `0x1ED` at `+0xF68`.

These are **proposed diagnostic physical reads**; their safety depends
on validating the descriptor types and the physical table-pointer
range. They do not prove SCTLR completed or establish a virtual
framebuffer mapping. `SCTLR OLD` has the MMU M bit clear, as expected
before XNU enables stage-1 translation.

## Next safe engineering work

1. Correlate live UEFI memory descriptors, ADT boot_args and pinned Mach-O
   physical/virtual load offsets; do not trust the FDT's unverified RAM bank.
2. Validate TCR_EL1, TTBR1_EL1 and table descriptor coverage for first
   post-ISB instruction VA and exception-vector VA before MMU is enabled.
3. Only then enable a post-MMU console via a verified mapped framebuffer
   alias or an independently proven UART/persistent trace. A direct physical
   GOP write after SCTLR can itself trigger a data abort.
4. Continue only with temporary `fastboot boot` and recoverability; never
   `fastboot flash`. Avoid further cosmetic stripes or arbitrary MMU patches.

Previous runs, source scripts and immutable kernel baseline must remain available.

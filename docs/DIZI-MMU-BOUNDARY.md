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

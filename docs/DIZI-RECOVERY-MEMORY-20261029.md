# dizi/SM7435P: recovery memory evidence (2026-10-29)

## Provenance and handling

These observations were parsed from files acquired via a root-capable Android
recovery environment on the physical Redmi Pad Pro (dizi/ruan family):
`dizi-recovery.dtb` (851,838 bytes), `dizi-recovery-devicetree.tar`,
`dizi-recovery-iomem.txt`, `dizi-recovery-dmesg.txt`,
`dizi-recovery-meminfo.txt` and `dizi-recovery-cmdline.txt`.

The DTB is a valid FDT v17 (3,675 nodes, 17,144 properties). Files in the
tarball were compared byte-for-byte with the DTB's `/model`,
`/memory/reg`, `/reserved-memory/splash_region/reg` and
`/reserved-memory/ramoops@80D00000/reg` properties; all four match.
SHA-256 of binary DTB:
`49354f92611c5b489f12f9c6352521eeaa5824e571083bc69511c70f401650c2`.

**This is the Linux recovery memory map, not a live UniXNU/UEFI allocation
map.** The Linux kernel, initrd, CMA, KASLR and dynamic carveouts occupy
addresses differently from EDK2 + DarwinBoot. The data are for *bounds
checking and conflict detection*, not allocation approval or proof that
XNU's TTBR1 mappings are correct. Raw files are deliberately NOT committed:
logs/device trees may contain unique hardware identifiers.

## Device identification and architectural facts

- DT model: `Qualcomm Technologies, Inc. Parrot QRD, DIZI based on SM7435P`.
- DT compatible: `qcom,parrot-qrd`, `qcom,parrot`, `qcom,qrd`.
- Linux 5.10.269; 8 ARM64 CPUs; PSCI 1.1; GICv3 with 988 SPIs.
- Generic virtual architectural timer frequency: 19.2 MHz, also verified
  by recovery dmesg.
- `/chosen/stdout-path`: `/soc/qcom,qup_uart@98c000:115200n8`,
  **but** dmesg says the console for that UART is *disabled*.
  A different UART at `0xA94000` registered as `ttyHS0` in Linux;
  this does not prove it can be used safely for XNU logging.
- RAM `/memory/ddr_size` is reported as 6, with about 5.92 GiB
  (6061 MiB) listed in DT `reg`. Linux maps fewer pages due to carveouts.

## DTB /memory/reg banks

Each entry is a 64-bit big-endian base and length pair
(`#address-cells=2`, `#size-cells=2`).

| Physical start | End inclusive | Length |
| --- | --- | ---: |
| `0x80000000` | `0xE8DFFFFF` | 1,678 MiB |
| `0xEA700000` | `0xFFFFFFFF` | 345 MiB |
| `0x800000000` | `0x83FCFFFFF` | 1,021 MiB |
| `0x840000000` | `0x8BAAFFFFF` | 1,963 MiB |
| `0x8BB100000` | `0x8BCEFFFFF` | 30 MiB |
| `0x8C0000000` | `0x8FFFFFFFF` | 1,024 MiB |

There is also a **zero-length** `/memory/reg` tuple at
`0xE9500000`; do not count it as allocatable RAM.
The 6 non-empty tuples sum to 6,061 MiB.

## Important discrepancy with the old reference-only Dizi FDT

The historical `data/dizi-fdt-observed.json` (duplicated in
`config/dizi-hardware.json`) was derived from a different `Mu-dizi.img`
FDT and lists **7,944 MiB** in its 7 banks, including
`0x8C0000000` + **3 GiB** (through `0x97FFFFFFF`).
The new *physical recovery* DTB instead lists **6,061 MiB**
in 6 non-empty banks, including `0x8C0000000` + **1 GiB**
(through `0x8FFFFFFFF`). No `/memory/reg` bank above
`0x900000000` is present in the physical recovery DTB.

This is **not** a minor carveout: the old image describes nearly
1.84 GiB more physical RAM than recovery's live DTB. The old
reference memory map cannot be used uncritically to address RAM
on this physical device.

**Dependency audit:** `ci/build_dizi_reference_adt.py` explicitly reads
the legacy `data/dizi-fdt-observed.json` bank and asserts the old 3 GiB
size. However that script labels its output **reference / ADT parsing
test only**, checks `memory_ownership_verified=false`, and prohibits
native kernel entry. The current manual `text-b` workflow reconstructs
a pinned Mach-O/boot image instead; it does not directly consume this
legacy JSON. Therefore the old FDT discrepancy is a definite stale
reference for *future* allocation decisions, **not established as the
cause of the current `text-b` MMU boundary**.

Preserve the old test for reproducibility, but use the recovery-derived
facts for conflict checks and require a real DarwinBoot/UEFI allocation
map for any new XNU memory ownership claim.

## Fixed and dynamic reserved regions critical for XNU

| Origin | Physical range | Meaning |
| --- | --- | --- |
| DT `/reserved-memory/splash_region` | `0xB8000000–0xBAAFFFFF` | 43 MiB splash/GOP reservation, matching the previously verified physical framebuffer base |
| DT `/reserved-memory/ramoops@80D00000` | `0x80D00000–0x80EFFFFF` | 2 MiB persistent Linux crash-record backend |
| Recovery `/proc/iomem` | `0x8F6B00000–0x8FDFFFFFF` | Dynamic high-memory reservation |
| Recovery `/proc/iomem` | `0x8FE005000–0x8FE1C4FFF` (several fragments) | Additional high-memory reservations |
| Recovery `/proc/iomem` | `0x8FE1C5000–0x8FFFFFFFF` | High-memory reservation through the end of the bank |

In the 1 GiB bank at `0x8C0000000–0x8FFFFFFFF`,
`/proc/iomem` reports reservations **beginning at `0x8F6B00000`**.
The first ~875 MiB are not shown as reserved by recovery's `iomem`,
while about 149 MiB at the top are marked reserved (with gaps).
**Do not treat the first 875 MiB as globally free**: this is
only an observation about Linux recovery, not an EDK2 memory map.

This invalidates any unconditional interpretation of the earlier
`data/dizi-fdt-observed.json` `ram_candidate` as a 1 GiB
firmware-safe XNU allocation. The old record already had
`validated_on_device=false`: keep it false. Fixed DT reserved-memory
does not capture all runtime allocations.

The former fixed splash reservation is inside a lower DRAM bank; a
pre-SCTLR framebuffer write is possible (and has been observed), but
**the framebuffer physical address is not automatically a valid virtual
address after `msr SCTLR_EL1`**.

### Other recovery-only allocations

- Recovery Linux kernel code at `0xA8000000–0xAA56FFFF` and data at
  `0xAA870000–0xAAB7FFFF`; these locations are **not** to be copied
  as XNU load locations.
- Recovery initrd described by `/chosen`:
  `0xB2FB9000–0xB7FFF0FB`, with Linux `iomem` reserving additional
  nearby pages. These are Linux-specific and differ under UniXNU.
- Recovery dmesg says `ramoops: using 0x200000@0x80d00000`.
  This may become a useful post-crash observation channel **only
  after** a deliberately designed, tested, non-corrupting use of that
  region across the EDK2/XNU/recovery transitions. Do not write there
  blindly.

## How this narrows the current MMU boundary

The latest physical `text-b` screenshot proves execution reached
the native pre-SCTLR hook. It does not read or display real TCR/TTBR1
registers, and its `PASS` lines are static strings. The
`postmmu-b` framebuffer writes were inconclusive because they use
physical address `0xB8000000` after enabling translation.

New recovery evidence confirms **the physical memory banks and
reserved-memory edges** but does not reveal:

- DarwinBoot's live `boot_args`, ADT memory ranges or UEFI
  `GetMemoryMap` immediately before `ExitBootServices`;
- actual `TCR_EL1`, `TTBR1_EL1`, `MAIR_EL1`,
  `SCTLR_EL1`, `VBAR_EL1` values in the XNU bootstrap;
- the physical location, table format, access permissions and
  descriptor coverage of the first post-ISB instruction's VA
  (`0xFFFFFFF0073F2358`), VBAR exception-vector VA and
  any intended framebuffer virtual alias.

## Next changes, without replacing UniXNU

1. Preserve the current known-good EDK2, DarwinBoot, `text-b`
   release and immutable baseline; keep manual `fastboot boot`
   and the B-series.
2. Instrument **before** SCTLR to read the actual EL1 registers and
   capture the physical pointer to the TTBR tables without modifying
   x0/x1/SP/NZCV. Prefer a safely allocated log buffer exported
   by DarwinBoot and bounded by *its own runtime UEFI map*.
3. Offline-walk the captured translation tables to confirm that
   the first post-ISB instruction and exception vectors have valid
   executable mappings, with correct `TCR` granule/PA/VA sizes.
   Test the framebuffer alias only if a valid descriptor exists.
4. Choose a post-MMU output path after that proof: valid VA-mapped
   text framebuffer or an independently proven serial/persistent
   channel. No guesswork using `0xB8000000` as VA.
5. Recovery DTB and `iomem` should NOT be installed directly into
   the XNU runtime or used to choose an unconditional load address.

No additional device root is required to begin the offline audit.

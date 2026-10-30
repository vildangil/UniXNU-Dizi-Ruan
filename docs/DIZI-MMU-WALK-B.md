# Dizi / UniXNU: page-table diagnostic B

This is the next test after the hardware-confirmed `regs-b` screenshot
of October 30, 2026. The image is built using the same manual
GitHub Actions workflow and keeps EDK2, DarwinBoot and native XNU
instructions unchanged.

The photograph shows `TCR=0x22A51A251A`,
`TTBR1=0x802F6E000`, and `VBAR=0xFFFFFFF0073ED000`.
The final VBAR suffix is **D000**. TCR specifies 4KiB
pages and a 38-bit TTBR1 virtual address range.

Both the next kernel instruction and the exception-vector address
share the L1 index `C0` and L2 index `39`.
`walk-b` collects the corresponding descriptor values before
attempting the native MMU transition. If L2 describes a 2MiB
block, no L3 reads are needed. If L2 references a table, the
diagnostic also collects separate L3 entries for kernel code
and exception vectors.

The `STATUS` field means: 0 = guard mismatch; 1 = L1 read;
2 = L2 reached; 3 = both L3 entries read. A zero L3 entry
with STATUS=2 may simply mean an L2 block was used.

The build is pinned to SHA-256
`8c5c1aba446897a7548461a05718d79ddfb5607cfd0745c5187d423ed3a05542`.
The previous `regs-b` and `text-b` options remain available.
This is an experimental, untested image, not a confirmed MMU fix.

Use temporary `fastboot boot` only, never `fastboot flash`.

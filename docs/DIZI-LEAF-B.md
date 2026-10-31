## New physical-device result — 2026-10-31

The owner supplied a clear LEAF-B photo:

```text
N 0000000804191000
F 0000000000000000
K 0000000804193003
C 00500008031EA683
H 00500008031F6683
X 00500008031F1683
V 00500008031ED683
S 0000000000000000
```

[Photo record](../data/dizi-leaf-b-hardware-photo-20261031.json),
[PTE decode](../data/dizi-leaf-b-pte-decode-20261031.json).
The panel matches LEAF-B; exact device-image SHA has not separately been stated
by the owner. The published download's SHA was independently verified earlier.

S=0 establishes completion of all four leaf reads. Each is a valid L3 page with
AF=1, AP=2 (privileged read-only), PXN=0, UXN=1, AttrIdx=0, SH=2, contiguous hint=1.
Physical pages are C=0x8031EA000, H=0x8031F6000, X=0x8031F1000, V=0x8031ED000,
matching the prior bootstrap mapping reference. These leaf bits permit EL1
instruction execution, but this is not a test of effective post-switch execution.
Parent table controls, SCTLR/MAIR and contiguous-group consistency also matter;
not all 16 members of each hinted group were read.

F=0 again confirms an absent framebuffer L2 entry in the prepared hierarchy.
Once stale TLB entries are invalidated, an unconditional access through that
alias would fault. In particular, text immediately after the first TTBR write
could still use a cached old mapping: it must not be misreported as proving a
new mapping. Native TLBI/DSB/ISB at 3EA124..12C is a meaningful later boundary.

Before a guarded alias repair/post-switch renderer, verify future live-stack
coverage (including the tracer frame), global data needed by the logger, mapping
attributes and guards. Static intstack symbols in this Mach-O are ...7BB0000 to
...7BB4000, but current SP was not captured; SP selection/boot-stack replacement
means those symbols alone do not establish the active stack. Do not guess it.
The exact native old/new physmap transition constraints in TABLE-B still apply.

Host decoder ci/decode_dizi_leaf_snapshot.py validates photo fields, checks PXN/
invalid/skipped cases, and explicitly leaves effective translation/stack proof
false. No extra device test is needed merely to repeat these same leaf readings.
Earlier pre-photo status below is historical.

---

# LEAF-B — kernel translation leaf evidence after TABLE-B result

2026-10-31: **GitHub CI succeeded and LEAF-B is published. No hardware result.**
[Run #41203388717](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41203388717), source `685c6b7bca7b424426ce4a1cc6058c1c0d627d96`.
[Download](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/download/dizi-xnu-latest-test/Mu-dizi-XNU-LATEST-TEST.img); actual downloaded bytes and GitHub asset digest match SHA below.
[CI JSON/emulation artifact](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41203388717/artifacts/13043741003).
[Publication evidence](../data/dizi-leaf-b-ci-20261031.json).

## Actual TABLE-B device observation

The new photo clearly reads:

```text
N 0000000804191000
V FFFFFFF008391000
L 2000000804192003
P 0000000804192000
F 0000000000000000
K 0000000804193003
S 0000000000000000
T 00000022A51A251A
```

The panel uniquely matches TABLE-B. Exact photo-image SHA has not separately
been stated by the owner. [Photo transcription](../data/dizi-table-b-hardware-photo-20261031.json)
and [descriptor decode](../data/dizi-table-b-descriptor-decode-20261031.json).

S=0 means the L1 and both L2 reads completed. **F=0 is an actual invalid entry**,
not a skipped-field placeholder: this new hierarchy lacks the diagnostic
framebuffer alias at the captured instant before switching. This explains why
unconditional old-alias printing after replacement is unsafe. It does not
prove the kernel halted or that replacement executed at all.

L is a table descriptor to 0x804192000; APTable=1 restricts EL0, with no parent
PXNTable/UXNTable bits. K is **a table descriptor, not an executable 2MiB block**:
it points to L3 at 0x804193000. Kernel leaf translations and permissions have
not yet been captured. The next entries are at 0x804193F50 (VM page), FB0 (helper), F88 (tracer) and F68 (vectors).
These are computed locations, not new hardware readbacks.

## What LEAF-B does

Keeps the four TABLE-B VM hooks and the early G MAP AUDIT at
0xFFFFFFF0073EA0B0, before native physmap metadata replacement. Reuses the same
root/L1/L2 guards and native allocation/RAM bounds, then, only for K type 3,
checks the L3 child against the same bounds, calls exact native phystokv under
the still-old mapping metadata, validates the converted VA, and reads four PTEs:

| Row | Value |
| --- | --- |
| N | Runtime prospective root PA |
| F | New framebuffer L2 descriptor |
| K | New kernel L2 descriptor |
| C | L3[0x1EA], native VM/probe/return page |
| H | L3[0x1F6], set_mmu_ttb_alternate/set_mmu_ttb helper page |
| X | L3[0x1F1], tracer code page |
| V | L3[0x1ED], vector page |
| S | Capture status |

S=0 means all reads completed. S=1..5 retain TABLE-B refusal meanings;
S=6 means K is not an L3 table (a block may be legitimate); S=7 means L3 child
outside conservative bounds; S=8 means converted L3 pointer rejected. Skipped
fields remain zero placeholders. Only interpret a leaf readback when S=0.

No new table writes, alias installation, AT instructions, IRQ/MMIO experiments
or post-switch renderer. Native flow remains untouched after replay. Stack
usage stays 320 bytes. TABLE-B and SWITCH-B remain selectable and byte-pinned.
Capturing valid code leaves is a prerequisite, not a complete guarantee for
post-switch logging: future stack/data mappings and memory attributes must also
be considered. A valid leaf alone does not establish IRQ/scheduler functionality.

## Validation

[Local build audit](../data/dizi-leaf-b-local-build-20261031.json),
[240-case emulation](../data/dizi-leaf-b-emulation-20261031.json).
The test executes actual native phystokv bytes for both conversions, checks all
GPR/SP/NZCV state and exact displayed values, and permits writes only to the
tracer stack/framebuffer. Added cases include invalid kernel L2, kernel block,
out-of-bounds L3 child, rejected L3 conversion and an invalid code leaf that is
reported honestly with S=0 rather than suppressed. Hardware MMU/cache/IRQ
behavior and live memory ownership are not modeled.

Boot SHA-256:
`0b5e0f0cebfc10d5e39b8a8f4db316740ad455efd2e154604ff3a2e4ee2e932f`.
Mach-O SHA-256:
`46cf768c38147b32cfda45c4fc65c9dd014d3ce5832961aa1edf7d4ce3bae50c`.

```sh
python3 ci/patch_dizi_mmu_leaf_b.py --input .cache/intermediate/Mu-dizi-XNU-FLOW-B-HIGH-RISK.img --output .cache/leaf-b.img --report .cache/leaf-audit.json
python3 ci/check_dizi_table_b_emulation.py --variant leaf-b --input .cache/leaf-b.img --output .cache/leaf-emulation.json
```

The existing manual xnu-mmu-ab-lab.yml gains leaf-b; default slot-b and old choices
remain. After successful CI/publication and SHA check, the next single test is:

```sh
fastboot boot Mu-dizi-XNU-LATEST-TEST.img
```

Photograph all N/F/K/C/H/X/V/S rows and G MAP AUDIT. Never flash experimental
images; cpus=1 and example=true remain unchanged. VM completion and userland
are still not established.

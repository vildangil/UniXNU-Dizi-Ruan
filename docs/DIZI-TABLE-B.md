# TABLE-B — bounded pre-switch L1/L2 evidence

2026-10-31: **GitHub CI passed and the image is published. No TABLE-B hardware test.**
[Successful run #41202475579](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41202475579), implementation `08f12cc3fab6577a0fb4d77404d052f274fee330`.
[Download TABLE-B](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/download/dizi-xnu-latest-test/Mu-dizi-XNU-LATEST-TEST.img); downloaded release bytes match the pinned SHA below.
[CI JSON/emulation artifact](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41202475579/artifacts/13042913736).
[Publication verification](../data/dizi-table-b-ci-20261031.json).
SWITCH-B's photo captured N=0x804191000, O=0x802F6E000, T=0x22A51A251A.
TABLE-B now reads descriptor contents, without modifying the kernel's tables.

## Design and limits

The probe runs at **0xFFFFFFF0073EA0B0**, after new table construction and qsort
return but BEFORE the metadata stores at 3EA0BC..3EA0E4. It reads the fixed native
root globals at 0xFFFFFFF00716ABB0/ABB8. The virtual global at ...ABB0
holds the native virtual pointer allocated with phystokv, stored at 3E97D8,
converted with kvtophys at 3E97DC and used by bzero at 3E97F4. TABLE-B obtains
that virtual pointer directly from its native global, rather than dereferencing a raw physical PA.

**Important placement correction:** at the old SWITCH-B G (3EA108), gptov mapping
metadata has already been replaced for the future physmap, while TTBR1 is still
old. An added phystokv call there could return a future-only VA. The unpublished
prototype was therefore moved earlier before final hashing/testing/publication;
no image containing that unsafe placement was published. Native execution then
continues through the original metadata copy and TTBR switch unchanged.

It requires exact photographed TCR=0x22A51A251A before any root dereference,
then a page-aligned high canonical root pointer. With 38-bit VA/4KiB pages the
initial L1 index is **0xC0, not 0x1C0**. It reads root[0xC0]. A non-table L1
(block/invalid/unsupported type) is reported without chasing a child pointer.

If it is a table descriptor, the masked child PA must be >= prospective root PA,
its entire page <= native next-allocation PA from 0xFFFFFFF00716C138, and its
entire page within native gPhysBase/mem_size. These conservative bounds can
reject a legitimate table outside that arena; rejection never bypasses native
code or expands the allowed range. They avoid reads of unrelated/MMIO addresses.

Only after those checks does the probe call the **exact native phystokv** at
0xFFFFFFF0073E8784. Inspection of the whole helper shows read-only mapping-range
selection and a bounds-checked fallback; the probe independently requires the
fallback RAM bounds, so an out-of-range child cannot enter its panic path.
Returned VA must also be page-aligned/high canonical before the two L2 reads.
This relies on the native allocator having initialized its table pages through
these mappings prior to G, as the inspected VM path does. Host checks cannot
prove that live kernel metadata or mappings are uncorrupted.

It reads L2[0x20] for framebuffer 0xFFFFFFF004000000 and L2[0x39] for code/vector
addresses. No descriptor is edited; no AT instruction, new vector handler,
PSCI call or unchecked post-switch framebuffer store is added. Existing guarded
pre-MMU diagnostic alias setup remains inherited from the known image.

Only four VM marker hooks remain (9 ENTRY, D TABLES, F MAP READY, G MAP AUDIT).
The eight FLOW-B hooks are restored to their exact native instructions. Their
restoration is bounded to those sites and verified by recovered ARCH-B SHA.
All historic variants stay selectable. This reduces trace size and stack traffic
while retaining important device checkpoints. First VM entry clears the known
2MiB framebuffer window; left markers and right numeric rows fit within it.

## Read the eight numeric rows

| Label | Value |
| --- | --- |
| N | Prospective TTBR1 root PA from native global ...ABB8 |
| V | Native virtual pointer to that root |
| L | New L1[0xC0] descriptor |
| P | Child table PA, if L is a table descriptor |
| F | Raw new L2[0x20] framebuffer descriptor, only meaningful with S=0 |
| K | Raw new L2[0x39] code/vector descriptor, only meaningful with S=0 |
| S | Probe status below |
| T | TCR_EL1 |

S=0: both L2 reads completed; **not proof of healthy mappings**.
S=1: TCR mismatch, no root read. S=2: root pointer rejected.
S=3: L1 is not a table (it may be a valid block, not necessarily a fault).
S=4: child outside conservative allocation/RAM bounds, no phystokv/child read.
S=5: converted child pointer rejected before L2 reads.
Unreached fields are zero placeholders; do not interpret them as memory readbacks.

F/K are raw L2 descriptors: type 3 means a further L3 table, requiring a later
leaf walk. Type 1 is a block whose PA/attributes/permissions must be decoded.
Invalid F with a usable K could explain lost display after TTBR replacement.
None of these readings demonstrate that the native switch actually happened.
The native AND/call and subsequent kernel flow run unchanged after this probe.

Peak tracer stack use: 320 bytes, saving snapshot x19/x20/x21/x30 separately;
common tracer preserves caller GPRs, NZCV and SP. The native phystokv uses integer
caller registers only on its accepted path. No extra SIMD clobbers are introduced.

## Validation and reproduction

Boot SHA-256:
`5479a94e36a2e3527131c9401ff98e1024bf3fc6f4356952a5e901cf720eb4e3`.
Mach-O SHA-256:
`0e501f962531c0143fb84727ec8c6370dc2cb61c30ec1ef0bdab927d1a63d1e5`.

[Local build report](../data/dizi-table-b-local-build-20261031.json),
[160-case emulation report](../data/dizi-table-b-emulation-20261031.json).
The emulator executes the actual native phystokv bytes, checks exact numeric
strings, original-vs-hook GPR/SP/NZCV state and forbids all writes outside the
stack and known framebuffer. Fixtures cover absent/present framebuffer, both native range-selection and fallback conversions, bad TCR,
misaligned root, invalid/block L1, child below/above bounds and bad converted VA.
It does not model real MMU/cache/interrupts or validate live memory ownership.

From the existing checkout with tools activated:

```sh
python3 ci/patch_dizi_mmu_table_b.py --input .cache/intermediate/Mu-dizi-XNU-FLOW-B-HIGH-RISK.img --output .cache/table-b.img --report .cache/table-audit.json
python3 ci/check_dizi_table_b_emulation.py --input .cache/table-b.img --output .cache/table-emulation.json
```

Next one physical test after successful CI and checksum verification:
`fastboot boot Mu-dizi-XNU-LATEST-TEST.img`. Photograph all eight numeric rows
and G. Never flash experimental images. Keep cpus=1/example=true; no actual
IRQ/scheduler/secondary CPU/rootfs/userland claim follows from descriptor reads.

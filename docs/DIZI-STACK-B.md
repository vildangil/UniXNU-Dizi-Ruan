## New hardware photo — active stack/data captured (2026-10-31)

The supplied rotated image matches STACK-B and reads:

```text
B FFFFFFF007BB3DD0
P 00600008039B3603
Q 00600008039B3603
D 0060000802F6A603
M 0060000802F6C603
L 0000000000003333
R 0000000804191000
S 0000000000000000
```

[Photo record](../data/dizi-stack-b-hardware-photo-20261031.json),
[decode/reference comparison](../data/dizi-stack-b-hardware-decode-20261031.json).
The owner has not separately stated the tested image checksum for this photo;
the published image bytes were independently SHA-verified before testing.

All four terminal reads completed at L3; no ancestor EL1 read-only flags are set.
P/Q/D/M have AF1, AP0 (private EL1 RW), AttrIdx0, PXN1/UXN1 and no contiguous hint.
The frame [B-384,B) lies within one page, 0xFFFFFFF007BB3000, translated to physical
0x8039B3000. Root-global page ...716A000 maps to 0x802F6A000 and metadata page
...716C000 maps to 0x802F6C000. All match the bootstrap linear reference using
previously photographed bases PA=0x802E04000, VA=0xFFFFFFF007004000.

B is inside the Mach-O static intstack range ...7BB0000..7BB4000 and exactly
intstack_top - 0xD0 (_arm_init frame) - 0x160 (arm_vm_init frame). Thus the
current SP is consistent with native bootstrap frames, rather than an assumed
firmware stack. This is a source/reference comparison, **not** an independent
old-root PTE walk or memory-content comparison. No effective post-switch access
or native TTBR execution is proven by this photograph.

## Next implementation requirements, not yet implemented

The code PTEs from LEAF-B and stack/data PTEs now provide concrete guard values.
A guarded diagnostic alias repair may target only the observed empty new L2[20],
with exact TCR/MAIR, hierarchy/ownership and framebuffer-reservation checks.
Before any write, compare current/prospective backing at runtime where needed;
do not silently turn agreement with a reference into a live old-table readback.
Validate the full hinted code PTE groups and sufficient stack/data pages.

Any failure must not leave an unconditional post-switch framebuffer hook active
without its mapping. One possible explicit diagnostic design is a reported,
intentional refusal before switching when guards fail; document that as a tracer
stop, not a native kernel hang. Preserve native opcodes/arguments on the success
path, and keep this read-only STACK-B selectable for rollback.

The first useful success checkpoint should be at ...73EA130, **after** native
TTBR1/TTBR0 writes and TLBI/DSB/ISB, with root-register readback verification.
Between the pre-gptov probe and that point, the inspected native straight-line
code writes metadata/root registers, not the installed alias PTE. Avoid adding
an unconditional VM-return renderer: pmap_bootstrap/later VM activity still need
review. Post-switch phystokv would use new metadata, but its returned root VA
must itself be mapped; do not introduce unchecked reads merely to test that.

No new image was produced for this photo analysis. Earlier pending-hardware
statements below are historical and superseded by the readbacks above.

---

# STACK-B — future active-stack and native-global mappings

2026-10-31: **GitHub CI succeeded; STACK-B is published. No hardware result.**
[Run #41205403802](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41205403802), implementation `7b1e86caede5b1d1a60e9cb2ff3a4a0c51a2154c`.
[Download](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/download/dizi-xnu-latest-test/Mu-dizi-XNU-LATEST-TEST.img); actual downloaded bytes and GitHub asset digest match the SHA below.
[CI JSON/emulation artifact](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41205403802/artifacts/13043368686).
[Publication evidence](../data/dizi-stack-b-ci-20261031.json).
LEAF-B established code-page readbacks, not live stack/data access after switching.
STACK-B captures the **actual active SP**, without assuming it is the static intstack.

## What is checked

Runs at the same G MAP AUDIT (0xFFFFFFF0073EA0B0), before native gptov metadata
replacement. No AT instruction, mapping edits, IRQ/PSCI call or post-switch stores.
Future roots come from native pairs ...716ABA0/ABA8 (TTBR0) and
...716ABB0/ABB8 (TTBR1). Both were allocated/zeroed before this site. Exact TCR
0x22A51A251A is required: each root has 38-bit VA, 4KiB pages, initial L1 width 8.

For each target, canonical low VA selects prospective TTBR0 and canonical high
VA selects prospective TTBR1. Tagged/noncanonical targets are conservatively
refused rather than guessed. Root PAs must be nonzero, page-aligned, <=40 bits;
the native virtual root must be aligned/high canonical before dereferencing.

The walker reads at most L1/L2/L3. A block or invalid entry ends the walk and
is reported as an actual terminal readback, even when invalid. A child table
may be chased only when its whole page is between the minimum native root PA
and native next-allocation PA, and within native gPhysBase/mem_size. The exact
native phystokv translates the child under the still-old metadata; its returned
pointer is checked before reading. These conservative bounds can reject valid
out-of-arena tables; refusals never expand into arbitrary reads.

APTable bit62 is accumulated through table descriptors, so a writable leaf
cannot conceal an ancestor's EL1 read-only restriction. Other controls and
memory attributes still require review; this is not effective access validation.

## Eight numeric rows

| Label | Meaning |
| --- | --- |
| B | Native active SP before the tracer |
| P | Terminal descriptor for B-8, top end of future tracer frame |
| Q | Terminal descriptor for B-384, bottom end |
| D | Terminal descriptor for 0xFFFFFFF00716ABB8, native root globals |
| M | Terminal descriptor for 0xFFFFFFF00716C048, physmap metadata |
| L | P/Q/D/M terminal levels in low four nibbles; ancestor EL1 RO bits at 16..19 |
| R | Future root PA selected for B-8 (TTBR0 or TTBR1) |
| S | P/Q/D/M status bytes, low to high |

Per-target status: 0=terminal descriptor actually read (it may be invalid),
1=TCR mismatch, 2=target canonicality refusal, 3=root refusal,
4=child outside allocation/RAM bounds, 5=converted pointer refusal.
Nonzero statuses make the corresponding zero field a placeholder. L also records
where a refused walk stopped; that level does not turn a placeholder into a readback.
Example L=0x3333 means all targets ended at L3; L=0xF3333 additionally records
ancestor read-only restrictions for all four. S=0x0404 means P and Q refused child
bounds while D/M completed. S=0 alone does not mean usable stack or valid mappings.

A 384-byte window is shorter than one page, so its endpoint pages cover the
whole future frame even if it crosses a page boundary. It does not qualify
arbitrarily larger logger frames. Valid/writable descriptors also do not prove
preservation of the current stack's physical backing: compare future physical
addresses against the verified current mapping/reference once B is known.
A different physical stack page could lose live frames despite valid permissions.
Contiguous hints also require checking group consistency. No current-vs-future
translation or frame-content identity is claimed by this probe. Snapshot usage is 192 bytes below the existing
192-byte tracer, total **384 bytes**. x19..x30 are saved in that frame; common
tracer preserves caller GPRs, SP/NZCV. Native phystokv uses integer callers only
on accepted paths. No SIMD registers are changed by the probe.

## Validation and limits

[Build report](../data/dizi-stack-b-local-build-20261031.json),
[240-case emulation](../data/dizi-stack-b-emulation-20261031.json).
The independent Python walker constructs both root hierarchies and predicts
exact eight-row output. Real AArch64/native phystokv bytes execute in Unicorn;
GPR/SP/NZCV effects must match the displaced native instruction. Writes outside
only the current frame/framebuffer are forbidden. Cases cover low/high SP,
page-crossing frame, read-only/missing stack, missing data, inherited RO, L2
blocks, invalid pointers, TCR mismatch, rejected child, rejected conversion,
noncanonical target and native range/fallback conversion paths.

This does not model real MMU/cache/IRQ effects, PAN/MAIR, corruption or live EFI
memory ownership. AP=0/AF=1 with no ancestor RO supports kernel-only writable
mapping at the descriptor level; EL0-accessible leaf permissions need PAN and
hierarchical review. It does not prove that either future root was installed.

Boot SHA-256:
`0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed`.
Mach-O SHA-256:
`396b1c94f6024efbd534957ea9fc6708ab1178997d2ae7fcf6ba61d3afc59f3d`.

```sh
python3 ci/patch_dizi_mmu_stack_b.py --input .cache/intermediate/Mu-dizi-XNU-FLOW-B-HIGH-RISK.img --output .cache/stack-b.img --report .cache/stack-audit.json
python3 ci/check_dizi_stack_b_emulation.py --input .cache/stack-b.img --output .cache/stack-emulation.json
```

Existing manual xnu-mmu-ab-lab.yml adds stack-b, retaining slot-b default and
all old choices. After CI/publication and checksum verification, one next test:

```sh
fastboot boot Mu-dizi-XNU-LATEST-TEST.img
```

Photograph all **B/P/Q/D/M/L/R/S** rows and G MAP AUDIT. No flash, CPU_ON,
example=false or full VM/scheduler/IRQ/rootfs/userland claim is implied.

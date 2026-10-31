# STACK-B — future active-stack and native-global mappings

2026-10-31: locally built and emulated; CI pending. No hardware result.
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
arbitrarily larger logger frames. Snapshot usage is 192 bytes below the existing
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

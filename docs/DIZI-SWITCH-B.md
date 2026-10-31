# SWITCH-B: numeric evidence before TTBR1 replacement

Status on 2026-10-31: locally built/emulated; owner has now authorized publication.
CI/release results will be recorded after completion. This is not a post-switch logger.

The new physical photo has clearly identifiable VM-B labels 9, A, B, C, D, F, G;
E is not readable/present in the photo. The photo matches VM-B, but its exact
image checksum has not separately been confirmed. G is before the native AND at
0xFFFFFFF0073EA108 and before the TTBR1 replacement call at 0xFFFFFFF0073EA10C.
This proves substantial progress inside native VM, not successful table switching
or a stopped kernel. The known VM-B intentionally prints nothing afterwards.

## Why another pre-switch probe is necessary

A safe post-switch framebuffer writer needs proof that the new tables map both
the writer's code and the framebuffer with correct attributes. The next root is
runtime-allocated; it cannot be recovered from file SHA or Mach-O segments alone.
Blindly writing through the old alias after the switch can itself fault. This
probe captures actual roots and TCR without reading arbitrary physical memory,
editing page tables, installing exception vectors or changing native flow.

At VM stage G, the right column is reserved for:

- `N <16 hex digits>`: original x8 before the native AND; the prospective TTBR1
  root loaded by the immediately preceding native instruction. High bits are
  intentionally printed; native code subsequently masks x0 to 48 bits.
- `O <16 hex digits>`: current TTBR1_EL1 read before replacement.
- `T <16 hex digits>`: current TCR_EL1, determining table geometry.

The left VM checkpoints 9..G remain. Old right-column flow markers are suppressed
so they cannot overlap the numeric fields. Stage 1 still clears exactly the known
first 2MiB alias. If N/O/T appear, they establish the pre-switch snapshot only.
Native switching is neither skipped nor simulated. The code makes no new MMIO,
PSCI or page-table edits. Existing guarded diagnostic alias setup is retained.

The snapshot uses a 64-byte frame below the tracer's existing 192-byte frame;
peak extra stack use is 256 bytes. It saves/restores its x19 and x30; the common
tracer restores all other live GPRs and NZCV before replaying the native opcode.
One possible EL2 trap on an EL1 register access is not modeled by the emulator;
TTBR1/TCR reads have already been used in earlier hardware diagnostic variants.
A missing numeric row does not isolate the underlying native fault.

## Validation

- Local build rejects source SHA mismatch, checks all 16 original opcodes and
  reviewed generated assembly, bounds the cave, and checks exact output hashes.
- 64 native-vs-hook emulation cases pass, including checking all three generated
  hexadecimal strings against nonzero simulated TTBR1/TCR and original x8.
- The prior VM-B binary was rebuilt byte-for-byte after factoring optional
  assembler/build arguments; its output hash remains unchanged. VM-B's 64
  emulator state comparisons still pass.
- Existing manual workflow has a draft switch-b option, with all rollback choices
  and default slot-b retained. Its shell syntax is checked, but no remote Actions
  run or full final workflow run is claimed in this session.
- No device run of SWITCH-B has occurred.

Boot SHA-256:
`b4e33fd8fc6064546e31083f589a691184c0e5fc52766ba32c05723597b31bc4`.
Mach-O SHA-256:
`5ada52955c15d1a68a2828e21b91312c6cb27a0ec6af8682c03189c2b6e25fbd`.
Payload and exact changed-byte bounds are in
[data/dizi-switch-b-local-build-20261031.json](../data/dizi-switch-b-local-build-20261031.json).

With LLVM/Python emulator activated, from the existing checkout:

```sh
python3 ci/patch_dizi_mmu_switch_b.py --input .cache/intermediate/Mu-dizi-XNU-FLOW-B-HIGH-RISK.img --output .cache/switch-b.img --report .cache/switch-audit.json
python3 ci/check_dizi_init_b_emulation.py --variant switch-b --input .cache/switch-b.img --output .cache/switch-emulation.json
```

One next physical test after matching the SHA:

```sh
fastboot boot switch-b.img
```

Photograph G and the complete N/O/T values. Those values are prerequisites to
reviewing the prospective table hierarchy and choosing safe post-switch evidence.
Do not interpret this preparatory probe as proving that alias preservation is
fixed. Native VM return, interrupt delivery, scheduler, rootfs and userland remain
unverified; cpus=1 and example=true stay unchanged.

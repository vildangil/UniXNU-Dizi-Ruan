## New device photograph — roots captured (2026-10-31)

The supplied photograph matches SWITCH-B and clearly reads:

```text
N 0000000804191000
O 0000000802F6E000
T 00000022A51A251A
```

9/A/B/C/D/F/G are identifiable; E is not identified. The tested image's exact
checksum has not separately been stated by the owner for this photo. The prior
published image checksum remains independently verified at release download.

The snapshot confirms a different prospective root, not installation of it.
TCR decodes to TG1=2 (4KiB), T1SZ=26 (38-bit high VA), IPS=2 (40-bit PA), initial
level L1 with **8 index bits**. Therefore framebuffer VA uses L1=0xC0, L2=0x20;
tracer, native switch and vector VAs share L1=0xC0, L2=0x39. Applying an unconditional
9-bit mask at L1 would incorrectly give 0x1C0 for these canonical high addresses.

The new initial L1 descriptor address for both paths is **0x804191600**;
old is 0x802F6E600. These are computed addresses, not descriptor readbacks.
We still need the descriptor and subsequent L2 entries to establish that the
new hierarchy retains the framebuffer and executable code mappings.

The exact native source shows the virtual root pointer stored at
0xFFFFFFF00716ABB0 (3E97D8), converted with kvtophys and its PA stored at
0xFFFFFFF00716ABB8 (3E97E8), then the root page zeroed (3E97F4). Before switching,
x27 points to the latter global (3EA100). This provides a source-backed candidate
for a bounded future read-only probe through the native virtual root pointer;
it does not authorize arbitrary dereferencing of the photographed PA.
Native phystokv contains range selection through mapping metadata: do not replace
it with a guessed constant virtual/physical offset for further levels.

[Hardware photo record](../data/dizi-switch-b-hardware-photo-20261031.json),
[decoded geometry](../data/dizi-switch-b-root-decode-20261031.json).
Reproduce the host calculation:

```sh
python3 ci/decode_dizi_switch_snapshot.py --new 0x804191000 --old 0x802f6e000 --tcr 0x22a51a251a --output /tmp/root-decode.json
```

The host decoder passed known indices and invalid-root/granule rejection checks.
No new boot image or extra hardware execution is implied by this analysis.
Earlier pre-photo status follows as history.

---

# SWITCH-B: numeric evidence before TTBR1 replacement

Status on 2026-10-31: **GitHub Actions successfully built and published** SWITCH-B:
[run #41200797504](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41200797504), implementation commit
`a2b00cff7620e068c039ea6ee8f95af7bd571a2e`. The release image was downloaded
back and its SHA-256 matches the pinned local image. **Not hardware tested.**
This is not a post-switch logger.

[Download published image](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/download/dizi-xnu-latest-test/Mu-dizi-XNU-LATEST-TEST.img).
[JSON audit/emulation artifact](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41200797504/artifacts/13042621469).
Artifact/log archive downloads into this environment were blocked on redirected
storage hosts; remote run status and actual release bytes were verified.
[Publication evidence](../data/dizi-switch-b-ci-20261031.json).

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
- Existing manual workflow offers switch-b, retains default slot-b and rollback
  choices. The full remote run #41200797504 completed successfully, including its
  build/test/artifact/publication steps.
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
fastboot boot Mu-dizi-XNU-LATEST-TEST.img
```

Photograph G and the complete N/O/T values. Those values are prerequisites to
reviewing the prospective table hierarchy and choosing safe post-switch evidence.
Do not interpret this preparatory probe as proving that alias preservation is
fixed. Native VM return, interrupt delivery, scheduler, rootfs and userland remain
unverified; cpus=1 and example=true stay unchanged.

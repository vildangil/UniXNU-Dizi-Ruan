# VM-B — locate native kernel VM progress before TTBR replacement

2026-10-31: **locally built and emulated, not hardware tested**. The owner
confirmed INIT-B SHA f093fce1722245c097b6712169130cef63a2a40b7aaf9588aec1e11225af377b
and every 9/A/B/C/D/E/F/G marker with a closer photo. Native execution reached
0xFFFFFFF0079B3B74 before mov x0,x19 and BL arm_vm_init. This supersedes the
previous conservative partial-G transcription. No VM completion is proven.

## Substantive findings

The exact photographed FLOW-B Mach-O disassembly shows arm_vm_init at
0xFFFFFFF0073E95BC reads the boot-argument structure in x1: fields at offsets
8, 16 and 24 initialize the virtual base, physical base and memory-size state;
0x20 supplies the next physical allocation position and 0x478 supplies an
optional actual-memory size. These are live values, **not extractable as actual
runtime arguments from a file's zero-filled globals**. A nonzero x0 clamps the
memory size; the earlier arm_init memory-limit parse supplies it. No new RAM
bank is authorized by these arithmetic operations.

Native phystokv, early_random, randomized physical mapping placement, kvtophys,
allocation-pointer advancement and bzero occur before segment extraction.
Multiple explicit cold assertion/panic paths validate page arithmetic, bounds,
and expected segment arrangements. No guard or call is skipped by VM-B.

The crucial switch is:

| Call VA | Exact target | Effect confirmed from helper instructions |
| --- | --- | --- |
| 0xFFFFFFF0073EA10C | set_mmu_ttb_alternate at 0xFFFFFFF0073F6214 | DSB SY; MSR TTBR1_EL1,x0; ISB; RET |
| 0xFFFFFFF0073EA120 | set_mmu_ttb at 0xFFFFFFF0073F6224 | DSB ISH; MSR TTBR0_EL1,x0; ISB; RET |

The name "alternate" must not be interpreted as TTBR0: it replaces **TTBR1 first**.
At 0xFFFFFFF0073EA124..12C native TLBI VMALLE1IS / DSB / ISB follow. The old
single-entry diagnostic alias is in the previous TTBR1 hierarchy. Its existence
in the newly constructed tables has not been established. Thus a post-switch
framebuffer store is unsafe and absence of further output is not a VM failure.
[VM disassembly](../data/dizi-arm-vm-init-disassembly.txt) includes the inspected
main body and branch targets; some cold targets lie beyond that listing.

[Layout audit](../data/dizi-vm-layout-20261031.json) verifies the exact input's
18 Mach-O segments: file bounds, filesize <= vmsize and virtual nonoverlap.
The 2MiB alias at 0xFFFFFFF004000000 does not overlap a segment; __PRELINK_TEXT
starts at 0xFFFFFFF00427C000, leaving 0x7C000 after the alias. This rules out a
file-level segment collision, not bad fixups, runtime memory ownership or a
missing mapping. The on-disk segments are not a live EFI GetMemoryMap.

Memory/SMP source audits still pass with the 6,061 vs 7,944 MiB conflict and
unapproved high-bank reservation. Preserve example=true/cpus=1. Native timer
frequency is known, timer IRQ delivery is not. CPU_DATA/stack/GICR/PSCI secondary
launch prerequisites remain unproven; no CPU_ON is added. Full XNU source builds
need the pinned macOS/Xcode workflow, while native prelink still needs its
runtime-qualified platform/ADT/memory inputs. No hardware driver can be claimed
fixed from these host checks. Scheduler, storage/rootfs and userland remain work.

## One next image

VM-B retains FLOW-B's right-column stages 1..8. It replaces INIT-B's now-proven
left-column continuation hooks with eight VM-internal hooks:

| Marker | Hook VA | Original opcode | What it establishes if seen |
| --- | --- | --- | --- |
| 9 VM ENTRY | 0xFFFFFFF0073E95DC | aa0103fa | VM prologue completed; before mov x26,x1 |
| A VM RAM | 0xFFFFFFF0073E9644 | f0ffec09 | Initial RAM arithmetic/storage reached |
| B VM PHYSMAP | 0xFFFFFFF0073E9698 | f0ffec13 | First phystokv returned |
| C VM ENTROPY | 0xFFFFFFF0073E96A4 | 92407415 | early_random returned |
| D VM TABLES | 0xFFFFFFF0073E97F8 | f0ffec08 | Two early allocation/zeroing sequences returned |
| E VM SEGMENTS | 0xFFFFFFF0073E9CD4 | f0ffec13 | Earlier segment extraction and guards passed |
| F VM MAP READY | 0xFFFFFFF0073EA104 | f9400108 | Native pre-switch table-pointer load reached |
| G VM SWITCH | 0xFFFFFFF0073EA108 | 9240bd00 | Table pointer loaded; BEFORE TTBR1 switch |

F and G are not guarantees that every earlier conditional branch executed.
G does not demonstrate either TTBR switch, VM return or full arm_init. If G is
last, the image intentionally adds no later framebuffer hook; native execution
can continue silently. A subsequent test then needs owned/mapped logging or a
verified native console, rather than an unconditional post-VM renderer.

Readability is fixed by clearing exactly the existing mapped first 2MiB once
at right-column stage 1, after the older legacy diagnostics ran, before drawing
the persistent two columns. It adds no mappings or reads/writes of other devices.
The original INIT-B image/source and SHA are unchanged and remain selectable.

## Reproduction and evidence

Boot-v4 SHA-256 (68,800,512 bytes):
`7947442d0f41c55ba60104cf9d91a1ed5eb932c766dd5c228323845500850ed2`.
Mach-O SHA-256:
`dd69bc6d1a34e99a25a9e4792d36fe08b43796e3f7220b5be063cc40a78ab929`.
Payload SHA, byte bounds and hooks: [build report](../data/dizi-vm-b-local-build-20261031.json).

From the existing checkout with LLVM activated:

```sh
python3 ci/check_dizi_vm_layout.py --input /tmp/flow-b.img --output /tmp/vm-layout.json
python3 ci/patch_dizi_mmu_vm_b.py --input /tmp/flow-b.img --output /tmp/vm-b.img --report /tmp/vm-audit.json
python3 ci/check_dizi_init_b_emulation.py --variant vm-b --input /tmp/vm-b.img --output /tmp/vm-emulation.json
```

The patcher SHA-checks FLOW-B, recovers and verifies underlying ARCH-B, validates
every native opcode, compares generated assembly with reviewed source, rejects
relocations/cave overflow and checks the final output hashes. All changes are
restricted to the existing cave and sixteen instruction hooks. No vector-handler,
PSCI call or new page-table edit is added. x0-x18/x30, SP and NZCV are retained;
x19-x29/SIMD are untouched except by the replayed native instruction itself.

64 native-vs-hook emulation comparisons pass, with a nonzero simulated old
framebuffer and explicit checks of background clearing. INIT-B's 64 comparisons
also pass unchanged. Emulation does not model real MMU/cache/interrupt timing.
Full predecessor build step from immutable fifth-NOSP through FLOW-B, INIT-B and
VM-B passed locally, including final image checksum. GitHub API still returns
proxy CONNECT 403; **no remote run/release was produced**. The existing manual
xnu-mmu-ab-lab.yml now offers vm-b and retains slot-b default/all old choices.

Next single physical test, after obtaining the checksum-matching image:

```sh
fastboot boot Mu-dizi-XNU-VM-B-HIGH-RISK.img
```

Photograph the clean two columns and last VM marker. Temporary boot only; never
flash experimental images. Do not infer fault location solely from absent text.

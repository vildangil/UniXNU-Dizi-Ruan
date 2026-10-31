## Stable / Dev Beta release split — 31 October 2026

Owner request: easy cross-computer access, no new push/PR-triggered builds, keep stable reference separate from experimental development. `dizi-xnu-stable` is an immutable SHA-pinned first NO-SP hardware-confirmed checkpoint (SHA ceb970d0...), NOT a working operating system. `dizi-xnu-dev-beta` is one rolling experimental IMG, overwritten on explicit owner-manual publish. The owner command `/run-dizi-fb8-readback` now publishes FB8-READBACK-B into dev-beta after all checks; manual `publish_release=true` also targets dev-beta. Existing `dizi-xnu-latest-test` stays archival and unchanged. One-time stable publication: `/publish-dizi-stable-reference` on control PR #1, or manual dispatch of publish-dizi-stable-reference.yml. Both release workflows are restricted to manual or exact owner issue comments. No push or PR trigger. See docs/DIZI-RELEASE-CHANNELS.md.

---

## FBFAIL8 owner continuation — 31 October 2026

The owner photographed `FBFAIL8` in the first physical `FB-BRIDGE-B` test. It is a deliberate pre-switch guard refusal, *not* evidence of native TTBR1 replacement or kernel panic. The pre-switch native L2 readbacks taken on an earlier LEAF-B boot were F=0x0 and K=0x0000000804193003, but FBFAIL8 can mean **either** new FB L2[0x20] nonzero or code L2[0x39] changed. The two *runtime* values must be measured in the same hook.

New separate source files `ci/dizi_mmu_fb8_readback_b.S.in`, `ci/patch_dizi_mmu_fb8_readback_b.py` and `ci/test_dizi_mmu_fb8_readback_b.py` implement that readback. The patched image is pinned to STACK-B and locally SHA-verified: `a0ca687c085a56460ac4307e304d6025f909ac250e4b4b9201173fde902a8335`. It prints SLOT L2 20, CODE L2 39, their full hex values, and one of FB8 SLOT BUSY / FB8 CODE DIFF / FB8 BOTH DIFF / FB8 MATCH STOP. It intentionally WFE-halts BEFORE any new PTE write or native switch, even if both values match. No post-switch code is called. **GitHub Actions #41215735588 succeeded** on the new owner-command route (artifact `dizi-mmu-ab-fb8-readback-b-41215735588`, ID 13047639826; exact output SHA verified). **Not yet tested on hardware.**

To build, select `fb8-readback-b` and `publish_release=false` in the existing MMU manual Actions workflow, or comment exactly `/run-dizi-fb8-readback` as owner `vildangil` on open control PR #1. The latter relies only on explicit issue_comment and forces no-release; other comments do not run the job. Do not enable push/pull_request triggers. Inspect CI success and SHA, then only a single temporary `fastboot boot` with recovery available. Photograph all readout rows. [Exact test details](DIZI-FB8-READBACK-B.md). Do not delete the earlier historical handoff or overwrite rolling release.

---

## Current framebuffer continuation — 31 October 2026

**Work had already implemented FB-BRIDGE-B before this session.**
This is now the NEXT experimental image to validate. Do not regenerate
it blindly or mistake the rolling release's `STACK-B` asset for
`FB-BRIDGE-B`.

Hardware chain: `alias-b` proved a working high framebuffer
VA `0xFFFFFFF004000000` → PA `0xB8000000` under the early TTBR1.
TABLE-B/LEAF-B/STACK-B photographed the **new native VM root**
`0x804191000`: L1[C0] `0x2000000804192003`, L2 table
`0x804192000`, missing framebuffer L2[20] = ZERO, valid EL1
executable kernel code/vector leaves, and read-write private
stack/data leaves with physical backing matching bootstrap references.
These are PRE-switch observations; true post-switch stack/code access
and contents are not yet independently verified.

`ci/dizi_mmu_fb_bridge_b.S.in` and
`ci/patch_dizi_mmu_fb_bridge_b.py` already provide one **guarded**
transfer of the exact Device-nGnRnE, PXN/UXN 2MiB alias descriptor
`0x00600000B8000C0D` to the new L2 slot PA
`0x804192100` BEFORE native TTBR1 replacement. The original
native `TTBR0/TTBR1`, `TLBI`, `DSB`, `ISB` remain unchanged.
The pre-hook displays `FB ALIAS READY` or `FBFAIL1..9` and refuses
a wrong mapping; after native barriers a new hook should display
`FB NEW TTBR OK` only after confirming root/MMU.

Pinned locally reproduced FB-BRIDGE-B output boot SHA256:
`4ff3a8f6839bc3ba9f33a91356b9f55e4e8cd65d6fafaf30391ba41e5babd195`
(68,800,512 bytes); source `STACK-B` SHA256
`0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed`.
The latest rolling release WAS STILL STACK-B when inspected at
2026-10-31 14:18 UTC. Verify digest again; **do not claim that
FB-BRIDGE-B has been built in Actions or physically tested.**

**New in the present continuation:** added
`ci/check_dizi_fb_bridge_contract.py`, and integrated it with the
existing manual `xnu-mmu-ab-lab.yml` `fb-bridge-b` selection and
manual/PR `validate.yml`. It checks actual pre-switch snapshots,
TTBR1 38-bit geometry, old/new roots, L2 entry, MAIR AttrIdx3,
Device descriptor permissions, next code+vector PTEs and native
stack/global page readbacks. It also examines assembler guard ordering,
the single new L2 write, DSB/readback, lack of CPU_ON, and performs
four deliberate negative tests. A separate JS audit directly over
current GitHub sources/evidence passed; the Python preflight has **not
yet passed a GitHub Actions run**. Any mismatch must fail closed.
Neither this nor local build pinning substitutes for device execution.

**Next single physical test once the manual GitHub Actions build
succeeds:** choose `main`, `fb-bridge-b`, `publish_release=true`
in the existing xnu-mmu-ab-lab.yml. Confirm final image SHA256 equals
`4ff3a8f6839bc3ba9f33a91356b9f55e4e8cd65d6fafaf30391ba41e5babd195`.
Only temporary `fastboot boot`. Send a photo of
`FB ALIAS READY`, `FB NEW TTBR OK`, or `FBFAILn`. Do not
try CPU_ON/other kernels or flash partitions. `FB NEW TTBR OK`
would prove a usable framebuffer immediately post-TLBI but NOT
full `_arm_vm_init` completion, driver readiness or OS boot.

More: [FB-BRIDGE-B design](DIZI-FB-BRIDGE-B.md).
The historical STACK-B / earlier text below remains useful but should
not be treated as the latest implementation status.

---

## Current experiment: FB-BRIDGE-B prepared in main (2026-10-31)

Read [docs/DIZI-FB-BRIDGE-B.md](DIZI-FB-BRIDGE-B.md) first.
This is an *experimental first fix for the missing high-VA framebuffer
alias in XNU's SECOND, natively constructed TTBR1 page hierarchy*.

The previous physically observed TABLE-B/LEAF-B showed new
L1[C0]=0x2000000804192003, new L2[20]=0 (missing framebuffer),
code L2[39]=0x804193003, new root PA=0x804191000, old
TTBR1=0x802F6E000, and stack/global future RW/NX L3 PTEs from STACK-B.
The missing mapping is why post-switch drawing through the existing
alias is UNSAFE until explicitly preserved; a frozen screen alone
does not prove a native VM hang.

New source in main:
ci/dizi_mmu_fb_bridge_b.S.in,
ci/patch_dizi_mmu_fb_bridge_b.py,
ci/test_dizi_mmu_fb_bridge_b.py.
Single manual workflow .github/workflows/xnu-mmu-ab-lab.yml now offers
fb-bridge-b as an OPT-IN variant, preserves default slot-b,
and reconstructs the exact STACK-B parent before patching.

Local GitHub artifact input SHA verified:
0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed.
New complete boot-v4 SHA:
4ff3a8f6839bc3ba9f33a91356b9f55e4e8cd65d6fafaf30391ba41e5babd195.
Embedded Mach-O SHA:
4ea7271ea3aefcd741dab55fff5f2f4bbfbec0252c38176da1038ca9cd3f2c3c.
ARM64 trace SHA:
1ad661288c843dab1bb6f5f1aa9567763da9d5aad1c8bf7801c359b391793379.
Rebuilt twice byte-identical locally. The AArch64 trace fits
1463/2032 bytes in the verified code cave; allowed mutations are
confined to that code cave and five four-byte hook locations.
Normal native TTBR helpers, TLBI/DSB/ISB remain untouched.

At 0xFFFFFFF0073EA0B0 (before native physmap metadata and TTBR
replacement), it checks nine invariants, calls the existing native
phystokv for PINNED old/new L2 page addresses, verifies the old
Device framebuffer descriptor 0x00600000B8000C0D, and if all match,
installs ONLY the new L2[20] 2-MiB Device descriptor. Status:
FB ALIAS READY success, FBFAIL1..9 intentional pre-switch WFE
refusal. At 0xFFFFFFF0073EA130 AFTER native TTBR write + TLBI/
DSB/ISB, checks new TTBR1=0x804191000, SCTLR.M=1 and then
prints FB NEW TTBR OK via high VA 0xFFFFFFF004000000. No
unconditional framebuffer access under unknown root.

**IMPORTANT STATUS:** this new variant has NOT yet been tested
in GitHub Actions and NOT hardware-tested. It does NOT establish
VM return, IRQ, scheduler, SMP, rootfs or a real framebuffer
driver. New LIVE L2 descriptor write is high risk, exact
hardware addresses may vary; guard failures intentionally
halt. Use ONLY temporary fastboot boot; NEVER flash.

Next: user or available tool manually dispatches the existing
workflow, variant=fb-bridge-b, publish_release=true; verify
boot SHA, then ONE physical boot and photograph left-side
FB ALIAS READY / FBFAILn and FB NEW TTBR OK.
On success, continue native arm_vm_init and pmap/IO-memory
work. On guard failure, fix cause instead of bypassing checks.
All earlier no-FB-BRIDGE statements below are historical.

---

## Latest hardware: STACK-B active SP/data PTEs (2026-10-31)

Photo reads B=FFFFFFF007BB3DD0, P=00600008039B3603, Q=same,
D=0060000802F6A603, M=0060000802F6C603, L=3333, R=804191000, S=0.
See data/dizi-stack-b-hardware-photo-20261031.json and
 data/dizi-stack-b-hardware-decode-20261031.json, docs/DIZI-STACK-B.md.
Photo-image SHA is not separately owner-stated; published image SHA was verified.
Earlier no-STACK-hardware-result entries below are historical.

All four L3 reads completed: AF1/AP0 private EL1 RW, PXN1/UXN1, no ancestor RO,
no contiguous hint. Future stack page PA=8039B3000; root-global page=802F6A000;
metadata page=802F6C000. They match previous bootstrap PA/VA reference bases.
SP is intstack_top - D0 - 160, inside static 7BB0000..7BB4000. This supports
native-stack and backing consistency, not independent old-root/current-content
comparison or effective post-switch access. Do not overstate that distinction.

Next: design guarded preservation of the observed missing FB alias in new L2[20]
and a checkpoint after native TLBI/DSB/ISB at 73EA130. Validate current/prospective
backing and exact code/stack/data permissions/groups before any table write.
Guard refusal must not let an unconditional unmapped post-hook run: a clearly
reported diagnostic stop before switching is one possible fail-closed design.
No such repair/post-hook is implemented yet. Read design limits in STACK-B doc.
Do not walk post-switch physmap blindly, nor add unconditional VM-return text.
Native switch completion, VM return, IRQ/scheduler/SMP/rootfs/userland unproven.

---

## STACK-B successfully published — 2026-10-31

[Actions #41205403802](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41205403802) succeeded on implementation
`7b1e86caede5b1d1a60e9cb2ff3a4a0c51a2154c` in main, including all build/test/
artifact/publication steps. Downloaded the release back: SHA `0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed`,
68,800,512 bytes; matches local pin and GitHub asset digest. JSON/emulation
artifact id 13043368686 exists (archive not separately downloaded). Evidence:
data/dizi-stack-b-ci-20261031.json, docs/DIZI-STACK-B.md.

No STACK-B hardware result. Next one temporary test: verify image SHA,
`fastboot boot Mu-dizi-XNU-LATEST-TEST.img`, photograph **B/P/Q/D/M/L/R/S** and
G MAP AUDIT. B=actual native SP, P/Q=terminal descriptors for B-8/B-384,
D/M=root-global/physmap metadata pages. L has level nibbles and inherited RO
bits; R is selected future stack root. S has four per-target status bytes.
Status0 means a terminal was read (it can be invalid), nonzero means skipped.
Compare resulting physical backing as well as permissions before a post-switch
logger: a valid writable page with different physical contents is not safe.
No alias repair/table edit, AT, post-switch access or CPU_ON was added.

Local 240 comparisons exercise both roots and native phystokv with a separate
host reference. Host decoder also refuses out-of-40-bit physical evidence and
keeps effective translation/stack-content identity explicitly unverified.
Native VM return, IRQs/scheduler, rootfs and userland remain unproven.

---

## STACK-B prepared: active-SP/data future-root walk (2026-10-31)

Owner asked to verify stack/data after LEAF-B code PTE capture. Read
 docs/DIZI-STACK-B.md. New read-only walker captures actual native SP and walks
prospective TTBR0 or TTBR1 according to canonical target VA, before gptov swap.
P/Q cover SP-8 and SP-384; D/M cover native root globals/physmap metadata.
L packs terminal levels and ancestor RO, S packs individual statuses; R selects
the root for SP-8. Four old VM checkpoints retained; no new table/alias edits,
post-switch writer, AT or CPU_ON. Peak stack384; cpus=1/example=true retained.
Local 240 comparisons pass against a separate Python walker, including actual
native phystokv bytes, low/high/page-crossing stacks, missing/RO/block mappings,
ancestor RO and refusal cases. Synthetic tests do not establish hardware access.

SHA 0aa6bc8c0af4ae12e8010d691e92c5e9e6578a91b89cbfda27aa063dc664d7ed.
CI/publication pending; no STACK-B hardware result. Next photo: B/P/Q/D/M/L/R/S
plus G MAP AUDIT. Status0 can mean a real invalid descriptor; nonzero means a
skipped terminal read, not a zero PTE. See decoder ci/decode_dizi_stack_snapshot.py.

---

## Latest hardware result: LEAF-B four code PTEs (2026-10-31)

Photo matches LEAF-B: N=804191000, F=0, K=804193003,
C=00500008031EA683, H=00500008031F6683, X=00500008031F1683,
V=00500008031ED683, S=0. See data/dizi-leaf-b-hardware-photo-20261031.json,
data/dizi-leaf-b-pte-decode-20261031.json and new section of docs/DIZI-LEAF-B.md.
Device-image checksum is not separately owner-confirmed; release checksum was
verified by downloading it. Existing no-hardware-result statements below are
historical and superseded by this photo.

All four raw leaves: type3 valid, AF1, AP2 privileged RO, PXN0/UXN1, AttrIdx0,
SH2, contiguous hint1. Physical pages match prior bootstrap code/reference:
8031EA000 (VM), 8031F6000 (TTBR helper), 8031F1000 (tracer), 8031ED000 (vectors).
This supports EL1 execution permissions at the leaf, not effective post-switch
execution. Contiguous groups/hierarchical controls and live stack/data coverage
are not fully proven. F=0 is again an actual absent new framebuffer mapping.

Next development: investigate active SP (not just static intstack symbols) and
logger data mappings; design guarded alias preservation and a checkpoint after
native TTBR writes AND TLBI/DSB/ISB at 3EA124..12C. A pre-TLBI text write may use
an old cached alias and is not proof that the new root maps it. No new mapping
writes or post-switch hook have yet been implemented in this documentation step.
Host decoder ci/decode_dizi_leaf_snapshot.py passes actual-photo and PXN/invalid/
skipped tests. Do not claim VM return, IRQs/scheduler, SMP, rootfs or userland.

---

## LEAF-B published and verified — 2026-10-31

[Actions #41203388717](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41203388717) succeeded on main implementation
`685c6b7bca7b424426ce4a1cc6058c1c0d627d96`; all build/test/artifact/publication
steps report success. Downloaded the actual rolling release image back:
SHA `0b5e0f0cebfc10d5e39b8a8f4db316740ad455efd2e154604ff3a2e4ee2e932f`, 68,800,512 bytes, matches local pin and GitHub digest.
CI JSON/emulation artifact id 13043741003 exists; archive not separately read.
See docs/DIZI-LEAF-B.md and data/dizi-leaf-b-ci-20261031.json.

No LEAF-B hardware result. Next one test: SHA-check the latest image, temporary
`fastboot boot Mu-dizi-XNU-LATEST-TEST.img`, photograph **N/F/K/C/H/X/V/S** plus
G MAP AUDIT. C=VM code leaf, H=TTBR helper leaf, X=tracer leaf, V=vector leaf.
S=0 means all reads completed, not valid/executable mappings or successful boot.
S=1..5 earlier refusals, 6=K not L3 table, 7=L3 allocation/RAM bounds,
8=converted L3 pointer refused. No extra table writes or post-switch renderer.
Keep cpus=1/example=true. Code leaves, stack/data mapping and attributes must be
checked before a guarded alias repair/post-switch logger. The only hardware
mapping result so far is TABLE-B's actual F=0, K=804193003, S=0.

---

## TABLE-B hardware: missing framebuffer alias; LEAF-B prepared (2026-10-31)

Latest photo reads N=804191000, V=FFFFFFF008391000, L=2000000804192003,
P=804192000, F=0, K=804193003, S=0, T=22A51A251A. See new hardware/decode
JSON under data/dizi-table-b-* and docs/DIZI-LEAF-B.md. Exact photo image SHA
is not separately owner-confirmed. S=0 makes F=0 an actual invalid L2 entry:
the prospective hierarchy lacks the diagnostic alias, explaining why old-alias
post-switch rendering is unsafe. This does not prove a native halt or switch.

K points to L3 at 804193000, not a block. Parent L APTable=1 (EL0 restriction),
PXNTable/UXNTable=0. Next proof needs VM/helper/tracer/vector PTEs. Prepared
LEAF-B captures them at the same pre-gptov G MAP AUDIT, adding bounded L3
conversion/reads, no mapping edits. Eight rows N/F/K/C/H/X/V/S; S=0 complete,
S=1..5 old guards, 6=K not table, 7=L3 bounds, 8=L3 VA refused. Peak stack320.
Local SHA 0b5e0f0cebfc10d5e39b8a8f4db316740ad455efd2e154604ff3a2e4ee2e932f.
240 emulation cases pass using actual native phystokv for both levels.
CI/publication pending; no LEAF-B hardware result. Next one photo should contain
all eight rows and G. Code leaf proof is necessary but future stack/data mapping
and memory attributes also matter before implementing post-switch logging.

---

## TABLE-B published after successful CI — 2026-10-31

Implementation `08f12cc3fab6577a0fb4d77404d052f274fee330` is in main.
[Manual Actions #41202475579](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41202475579) succeeded and published the existing
single-image rolling release. Downloaded actual release bytes and GitHub asset
digest both match SHA `5479a94e36a2e3527131c9401ff98e1024bf3fc6f4356952a5e901cf720eb4e3` (68,800,512 bytes).
CI artifact id 13042913736 contains JSON/emulation reports; archive contents
were not separately downloaded. Evidence: data/dizi-table-b-ci-20261031.json.

Read docs/DIZI-TABLE-B.md. Four VM hooks; final **G MAP AUDIT is now at 3EA0B0**,
earlier than SWITCH-B's G, before gptov metadata is overwritten. This placement
is essential: calling phystokv at old G could return a future-only VA before
TTBR1 replacement. It was corrected before publishing; no unsafe prototype was
published. Local 160-case emulation covers both native phystokv paths and guard
refusals. Existing SWITCH-B remains byte-identical/selectable.

No TABLE-B hardware result. Next single test: verify SHA, temporary
`fastboot boot Mu-dizi-XNU-LATEST-TEST.img`, photograph all **N/V/L/P/F/K/S/T**
rows plus G MAP AUDIT. S=0 means two L2 reads completed, not good mappings;
nonzero S means some fields are placeholders. F/K may point to L3, so decode
raw types/attributes and complete leaf proof before installing any mapping or
post-switch writer. No new page-table writes/CPU_ON; cpus=1/example=true retained.

---

## TABLE-B prepared: bounded descriptor reads (2026-10-31)

See docs/DIZI-TABLE-B.md before the next test. TABLE-B starts from pinned FLOW-B,
restores its eight old hooks and installs four VM hooks. At 0xFFFFFFF0073EA0B0 (G MAP AUDIT), before replacing gptov metadata, it captures native
virtual root, L1[C0], then (only for a table and bounded native-allocated child)
uses the exact read-only native phystokv and reads L2[20]/L2[39]. It never edits
tables or prints after the switch. S status separates skipped reads from zeros.
Numeric labels N/V/L/P/F/K/S/T; peak tracer stack 320 bytes. Old SWITCH-B remains
byte-identical after optional shared-builder refactoring.

Local boot SHA 5479a94e36a2e3527131c9401ff98e1024bf3fc6f4356952a5e901cf720eb4e3.
160 native-vs-hook fixture comparisons pass, including actual phystokv execution,
exact displayed hex values and no writes to tables/metadata. CI/publication is
pending; do not claim TABLE-B hardware success. Existing manual workflow only,
slot-b stays default. Next photo should include every numeric row and G.

The green flash observation is recorded as an unspecific display change; it is
not proof of TTBR switch execution. VM completion, IRQs/scheduler, SMP, rootfs
and userland remain unverified. Do not add a post-switch writer or alias mapping
until the new descriptors have been decoded and leaf/attribute checks completed.

---

## Latest hardware photo: SWITCH-B numeric snapshot (2026-10-31)

Read the new section of docs/DIZI-SWITCH-B.md and
 data/dizi-switch-b-hardware-photo-20261031.json. Photo clearly reports:
N=0x0000000804191000, O=0x0000000802F6E000, T=0x00000022A51A251A.
9/A/B/C/D/F/G are identifiable; E is not identified. Exact photo-image SHA is
not separately owner-confirmed, although the released source image was hashed.
The old statements below saying no SWITCH-B photo exists are superseded.

TCR gives TTBR1 4KiB, 38-bit VA, 40-bit PA, initial L1 index width 8 bits.
Framebuffer indices: L1 C0 / L2 20; code/vector: L1 C0 / L2 39.
Calculated next-root L1 entry PA is 0x804191600; no entry content was captured.
Host decoder ci/decode_dizi_switch_snapshot.py checks these indices and rejects
invalid roots/granules; report in data/dizi-switch-b-root-decode-20261031.json.

Native root virtual-pointer provenance was traced through 3E97D8..3E97F4 to
virtual global 0xFFFFFFF00716ABB0 and physical global ...ABB8. Use this known
native pointer to design a bounded read-only hierarchy probe, not an unchecked
physical dereference. phystokv has metadata/range logic, so do not guess an
universal physical-to-virtual offset. Do not inject mappings before capturing
and checking descriptors. No new image is produced for this documentation step.

The last confirmed point remains BEFORE native TTBR1 replacement. Numeric roots
do not establish that either switch happened, that VM returned, or that missing
later output means a halt. Native IRQs/scheduler/rootfs/userland remain unverified.

---

## SWITCH-B now published and SHA-verified — 2026-10-31

Owner explicitly reauthorized publication. Implementation commit
`a2b00cff7620e068c039ea6ee8f95af7bd571a2e` is in main, verified by ls-remote.
Manual [Actions #41200797504](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41200797504) completed **successfully** and published
[Mu-dizi-XNU-LATEST-TEST.img](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/download/dizi-xnu-latest-test/Mu-dizi-XNU-LATEST-TEST.img) to the existing one-image rolling release.
The release was downloaded back and independently hashed:
`b4e33fd8fc6064546e31083f589a691184c0e5fc52766ba32c05723597b31bc4`.
GitHub asset digest agrees; size 68,800,512 bytes. Artifact id 13042621469 holds
CI JSON/emulation reports. Log/artifact redirected storage hosts are blocked for
local downloads, so do not claim those archives were inspected; successful run
status, artifact metadata and actual release image bytes were verified.
See data/dizi-switch-b-ci-20261031.json and docs/DIZI-SWITCH-B.md.

**No SWITCH-B hardware result yet.** Next one physical test: verify image SHA,
`fastboot boot Mu-dizi-XNU-LATEST-TEST.img`, photograph G plus complete N/O/T.
N is original x8 before native root masking, O=current TTBR1, T=TCR. No
post-switch writer/table edits were added. Native VM return, IRQs, scheduler,
rootfs and userland remain unproven. Earlier unpublished/pause entries below
are historical and superseded by this owner-authorized publication.

---

## Publication resumed by owner — 2026-10-31

The owner explicitly lifted the accidental publication pause and authorized
continuing SWITCH-B publication. GitHub API access now works through the
published environment's configured api.github.com allowlist. The implementation
and existing manual workflow are being published directly to main; CI/release
results must be recorded after the run finishes. No hardware SWITCH-B result.
The local-draft/pause status in earlier entries below is historical.

---

## New unpublished work: VM-B photo and SWITCH-B draft (2026-10-31)

Publication is stopped by the owner's latest instruction. Do not push changes,
dispatch/publish experimental releases or repeat prior environment draft edits
without renewed authorization. Latest local changes are not in remote main.

New photo matches VM-B and shows 9/A/B/C/D/F/G clearly; E is not identified.
Exact VM-B image checksum is not separately owner-confirmed. G is pre-TTBR1
replacement at 0xFFFFFFF0073EA108, not evidence of VM completion or a hang.
See data/dizi-vm-b-hardware-photo-20261031.json.

Prepared a local SWITCH-B draft: retain left VM markers, reserve right column
for N=new root (original x8), O=current TTBR1, T=TCR. It collects runtime
prerequisites for a safe table review without any new page-table/MMIO writes
or post-switch framebuffer access. Read docs/DIZI-SWITCH-B.md before using it.
Boot SHA b4e33fd8fc6064546e31083f589a691184c0e5fc52766ba32c05723597b31bc4.
64 snapshot/state emulator checks pass; old VM-B reproduces byte-for-byte and
its 64 state checks pass. Workflow changes are local only; no remote CI claim.
Next device test, if using this locally built draft: temporary fastboot boot
.cache/switch-b.img and collect complete N/O/T values plus G. The native table
switches still continue untouched; root values alone do not prove mappings.

No full OS proximity claim is justified: VM completion, IRQ/scheduler,
rootfs/drivers and userland remain unproven. Keep cpus=1 and example=true.

---

## Latest: owner confirms INIT-B through G; VM-B prepared (2026-10-31)

The owner explicitly confirms 9 CURRENT THREAD and **all A..G**, supplying a closer
photo. SHA f093fce1…377b was already explicitly confirmed. G is now confirmed at
0xFFFFFFF0079B3B74, not provisional; it is before the native mov x0,x19 and
arm_vm_init call at 3B78. See updated hardware JSON. Earlier conservative photo
transcriptions below are historical and superseded by this direct observation.

Read [DIZI-VM-B.md](DIZI-VM-B.md) for the next implementation and actual VM analysis.
VM-B is locally built/emulated only, with clean background and eight VM-internal
stages before TTBR replacement. It starts from pinned FLOW-B; original INIT-B is
unchanged. Existing manual workflow adds vm-b; no new workflow or automatic image
trigger. Boot SHA: 7947442d0f41c55ba60104cf9d91a1ed5eb932c766dd5c228323845500850ed2.

Important discovered boundary: at 0xFFFFFFF0073EA10C, set_mmu_ttb_alternate writes
TTBR1, and at 0xFFFFFFF0073EA120 set_mmu_ttb writes TTBR0. VM-B's G is just BEFORE
the first replacement. Never add an unconditional framebuffer writer afterwards.
18-segment layout checks pass, including alias separation from PRELINK_TEXT;
live boot_args/EFI map ownership and post-switch mappings are still unvalidated.
No speculative driver/VM guard bypass was made. cpus=1 and example=true remain.

64 VM-B emulation cases and 64 unchanged INIT-B cases pass; full workflow build
step locally reproduced from fifth-NOSP and verified final SHA. Remote API still
CONNECT 403; no GitHub Actions run, release publication or VM-B hardware test.
Data JSON distinguishes hardware INIT-B from locally built VM-B. Next physical
test is one checksum-verified VM-B temporary fastboot boot; collect last VM stage.

---

## New physical-device photo received — 2026-10-31

The owner supplied a photo matching INIT-B's two-column layout. Right-column
1..8 are readable. New left-column stages 9..F are identifiable despite
superimposed legacy diagnostic text. The final expected G VM CALL line appears
present but is partly obscured: keep its transcription provisional. Conservatively,
F PROCESSOR at 0xFFFFFFF0079B3AF0 means processor_bootstrap returned, conditional
on the image matching the pinned implementation. Even a confirmed G is BEFORE
arm_vm_init, never proof of its call/return or full VM initialization.

See [structured photo evidence](../data/dizi-init-b-hardware-photo-20261031.json).
The owner explicitly confirmed the full boot image checksum
`f093fce1722245c097b6712169130cef63a2a40b7aaf9588aec1e11225af377b`.
This is owner-confirmed provenance, not an independent assistant device-side hash.
This new observation supersedes earlier statements that no INIT-B physical photo
exists; earlier local build/CI reports retain their historical meaning.

A confirmed instrumentation display defect: left-column foreground glyphs overlap
legacy ENTRY/ALIAS/SCTLR/GUARD/TPIDR/ARCH messages. No background clear was added
when moving these markers to x20. Fix readability in a subsequent variant, preserve
the photographed INIT-B byte-for-byte, and do not interpret unreadability as a
kernel fault. Next investigate the F-to-VM path and mapping-safe post-VM output.
The photo alone cannot locate a hang, prove VM completion, IRQs, scheduler or SMP.

---

## Continuation session 2026-10-31 — INIT-B locally verified

Read [DIZI-INIT-B.md](DIZI-INIT-B.md) first for the new continuation analysis,
precise hook semantics, hashes and remaining work. Latest physical evidence is
still FLOW-B. INIT-B is **locally built and CPU-emulated only**, not hardware tested.

- Confirmed local baseline main bcd0cf2210c9718240914ab3fc4953fb387f6249 matches remote HEAD.
- Downloaded rolling FLOW-B and checked the full 3e587f8d… hash; inspected exact Mach-O symbols/instructions.
- Added init-b with 16 total stages, relocated BL and ADRP with correct native link/page targets, and persistent two-column output.
- Final G VM CALL is BEFORE arm_vm_init (3B74), deliberately avoiding unsafe post-VM framebuffer writes; no VM-return claim.
- No vector handler or new MMIO/PSCI/page-table writes. cpus=1 and example=true retained.
- Output boot SHA: f093fce1722245c097b6712169130cef63a2a40b7aaf9588aec1e11225af377b.
- Output Mach-O SHA: dbe2c7cdcdf65214d1e3360a0c674f07a91fd41e96487939ab36f944c5eadecf.
- 64 Unicorn native-vs-hook comparisons pass; memory/SMP audits and read-only PSCI helper AArch64 compile pass.
- New artifacts under data/dizi-init-b-* describe LOCAL checks, never additional hardware measurements.
- Installed clang/LLVM 19 without root via signed Debian indices and local package extraction. Saved environment install_script/start_skill and required api.github.com allowlist addition.
- Git over the injected proxy works outside the command sandbox. API CONNECT is denied (403); saving network draft did not apply it. No remote Actions run or new release has been produced. User must apply environment network settings before API dispatch can be retried. No new token requested.
- Native full-XNU source build requires pinned macOS/Xcode runner; prelink runtime qualification, live memory ownership, ADT/platform, GIC/timer IRQ, scheduler/rootfs remain unverified. No speculative subsystem bypass was made.
- Next: restore API access, run existing manual workflow on main with init-b, verify output hash, then request one temporary fastboot boot and photo of both columns. Preserve photographed FLOW-B for rollback.

---

# AI / Work handoff — UniXNU on Redmi Pad Pro dizi
**Updated:** 2026-10-31. **Status:** physical-device `flow-b` reached all eight checkpoints inside XNU `_arm_init`.

**This file is intended for a fresh ChatGPT Work session AND for returning to the original chat.** Read it, current `main`, the data files and the CI/release before starting work. Update this file on every substantial work session, including new code, verified build status, remaining blockers, and the next requested hardware test.

## Project and owner constraints

- Primary repository: https://github.com/vildangil/UniXNU-Dizi-Ruan
- Shared SoC repository: https://github.com/vildangil/UniXNU-sm7435-common
- Historical/reference work only: https://github.com/vildangil/dizi_IpadOS_maybe and the older `ios-sweet` experiment. **Do not transplant/replace UniXNU with ios-sweet or rewrite the project as a hybrid.** Examine historical results only to reuse validated ideas.
- Upstream project: https://github.com/UniXNU/UniXNU .
- Target: Xiaomi Redmi Pad Pro (code `dizi`, Qualcomm SM7435/Parrot). `ruan` unverified.
- User wants a *working UniXNU/XNU boot*, not cosmetic markers or a fake simulated OS; early OS initialization, panics, clock/interrupts, IOKit/rootfs and userland are still major missing milestones. Full boot within one/two chats is a **goal**, not a guarantee.
- **Modify `main` directly. Do not create separate branches, PRs, tag clutter or new one-off workflows.** The owner explicitly removed extra branches. If branch protection blocks a safe direct update, explain the blocker; do not imply the change was merged.
- Existing `.github/workflows/xnu-mmu-ab-lab.yml` is **manual workflow_dispatch only**. Keep it that way. Its `slot-b` default remains the safer option. Add advanced options there, not new workflows. Prefer user-confirmed build and source SHA pins, preserve rollback variants.
- No overwriting known working EDK2 / DarwinBoot / XNU baseline. Keep exact SHA checks for every binary change; verify original ARM64 displaced instructions and all branch/call returns, page-table flags, vector table and register/stack preservation. Avoid false-positive tracer messages.
- Owner runs ONLY temporary **`fastboot boot <image>`** on physical tablet. Never instruct `fastboot flash`/partition erases; keep Android recovery and fastboot functional. The assistant/Work has no physical control of the device and must not claim hardware testing on its own. Do not enable `cpus=2` or call PSCI CPU_ON without explicit approved hardware experiment and secondary CPU data/stack/GIC prerequisites.
- Prefer GitHub Actions artifacts/Releases over sandbox downloads. Rolling release `dizi-xnu-latest-test` uses ONE `Mu-dizi-XNU-LATEST-TEST.img` asset, overwritten only by user-authorized manual builds. Check SHA and run result before claiming a new artifact.
- User speaks Russian; communicate results in Russian, succinctly. Avoid asking questions already answered in this document. Do substantial GitHub work autonomously and then ask for one necessary device photograph/log.
- User specifically requested broader **multi-stage diagnostics in ONE image**, not a new boot for each tiny marker. Preserve readable TEXT output rather than colored framebuffer bars and keep messages visible for photographic capture. Preserve native XNU, not patch arbitrary codes that merely make a message appear.

## Verified CURRENT hardware results — authoritative baseline

Last photographed image in user chat: `/mnt/data/2458.jpg` in the previous conversation only (may not be mounted in new Work chat); authoritative transcription is in
[`data/dizi-flow-b-eight-markers-hardware-20261031.json`](../data/dizi-flow-b-eight-markers-hardware-20261031.json).

The **physically tested `flow-b`** image prints:
```
XNU ENTRY
PRE ALIAS ARMED
POST SCTLR OK
GUARD PASSED
TPIDR DONE
ARCH REGS OK
1 PROLOGUE
2 TBI RETURN
3 KC REBASE
4 CPU DATA
5 PE PLATFORM
6 TIMER WFE
7 CPU TOPO
8 THREAD READY
```
All **eight stage names** are visible in the most recent on-device photograph. The underlying UniXNU EDK2 menu is just old framebuffer contents, **not** evidence of returning to firmware.

The final marker is at native XNU `_arm_init` virtual address **`0xFFFFFFF0079B3ABC`**, before displaced `mov x20,x0`. The native call to **`_thread_bootstrap`** immediately before that site returned. It **does not prove** that the displaced instruction executed, the thread/scheduler works, or any subsequent call or full `_arm_init` finished. **The photograph does not establish the precise point where execution stops.**

`flow-b` boot-v4 SHA-256:
`3e587f8da8e3cf2e3de5ba04d3bcd19808c30dffc3ddcf8699ce52eb0261888c`.
Embedded Mach-O SHA:
`b740835898ca1be232e733c76af967a66fbe025c3b8e48f34c2febb8f889efc7`.
Payload SHA:
`dbdb592ce93c7ad750874c32423b14d4ffa7499ef54a82b3e880cd7bd73f2c6f`.

GitHub Actions successful manual `flow-b` run:
https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41194255999 .
Rolling release:
https://github.com/vildangil/UniXNU-Dizi-Ruan/releases/tag/dizi-xnu-latest-test .
At handoff it contains `Mu-dizi-XNU-LATEST-TEST.img` with `flow-b` SHA above.
Always recheck current release: it is a **rolling** asset and may change.

Previous hardware-confirmed checkpoints:
- `alias-b` corrected after a mistaken MAIR transcription: `POST SCTLR OK`, `GUARD PASSED` (native `SCTLR_EL1` write/ISB and post-MMU high VA framebuffer write, native compare guard reached/passed). SHA `ef9832e794860eedb6b2e11ba08edcf99eae030152d6dcc9496475d9b278c7dd`. Old `ALIAS GUARD FAIL` was **our own typo** `0x008B` vs real `0x00BB` in MAIR byte.
- `deep-b`: `TPIDR DONE`, `ARM_INIT CPU0` printed. SHA `4acf22fe3b0fb389ccc057b591b7c41fc57e0e0c32eaa246342f34e85c232c45`.
- `arch-b`: `ARCH REGS OK` printed, verifying `CurrentEL=EL1`, `CNTFRQ_EL0=19,200,000`, MMU `SCTLR.M=1`, `TPIDR_EL1=0`, `MIDR` nonzero and bootstrap `MPIDR` affinity 0. SHA `58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`.
- `slot-b` screenshot confirmed TTBR1 L1 C0 / L2 20 candidate entry zero at that instant (`STATUS=2`); `fbwalk-b` confirmed TTBR0 low VA `0xB8000000` was **unmapped** (`STATUS=1`). Kernel instruction and VBAR were mapped by valid executable L2 block from `walk-b`.

Important screenshot-measured register/mapping values:
```
TCR_EL1       0x00000022A51A251A
TTBR1_EL1     0x0000000802F6E000
TTBR0_EL1     0x0000000802F6D000
MAIR_EL1      0x0C0804FF00BB44FF  # BB, never misread as 8B!
VBAR_EL1      0xFFFFFFF0073ED000  # D000, not 0000
SCTLR_EL1 old 0x0000000030D00808
x22           0xFFFFFFF007004000
x23           0x0000000802E04000
TTBR1 L1      0x0000000802F70003
kernel L2     0x0000000803000601  # 2-MiB block
alias L2      0x0000000000000000  # empty before alias-b
framebuffer physical   0xB8000000; display 1600x2560 stride 6400
framebuffer reserve    43 MiB (0xB8000000..0xBAAFFFFF)
framebuffer high VA    0xFFFFFFF004000000
alias block descriptor 0x00600000B8000C0D # AttrIdx3=0 Device nGnRnE, NX, AF, nG
```
The guarded alias modifies ONE L2 entry before SCTLR. It is an instrumentation workaround, not an implemented framebuffer driver or reusable VM allocator.

## Repository code and validation

Current `main` files of interest:
- `board.toml`: **example=true**; native full XNU still intentionally incomplete/blocked by configuration. Default kernel args `-v cpus=1`. Do not set example=false just to force a build without validating hardware integration.
- `feeds.toml`: SoC common pinned to `22a71774c8ebf8ca6f2816bf774ff05d6b96e828`. The common repo may have newer README commits; review the pinned *code*, not blindly its latest main.
- `dts/dizi.dts`, `dts/sm7435-smp.dtsi`, `config/dizi-hardware.json`, `data/dizi-fdt-observed.json`, `ci/check_dizi_memory_map.py`, `ci/check_sm7435_smp.py`.
- `ci/patch_dizi_mmu_flow_b.py`, `ci/dizi_mmu_flow_b.S.in`, `ci/dizi_mmu_flow_b_payload.b64`, `ci/check_dizi_flow_b_source.py`: checked original opcodes, SHA, source assembler equivalence, code cave.
- `ci/patch_dizi_mmu_arch_b.py`, `ci/patch_dizi_mmu_deep_b.py`, `ci/patch_dizi_mmu_alias_b.py`, and prior variants.
- `docs/DIZI-FLOW-B.md` (detailed stage addresses), `docs/DIZI-DEEP-SMP-PREFLIGHT.md`, `docs/DIZI-MMU-ALIAS-B.md`, `docs/DIZI-MMU-BOUNDARY.md`, `CHANGELOG.md`, hardware evidence under `data/`.
- `.github/workflows/xnu-mmu-ab-lab.yml`: manual pinned build+artifact+one-asset release. `.github/workflows/validate.yml`: source-only preflight including memory and PSCI compile. Other workflows build native XNU source and prelink candidate; they do **not** imply a bootable OS.
- The raw Mach-O is 51,941,376 bytes. SHA-pinned Android boot-v4 used for `flow-b` is 68,800,512 bytes. It embeds a FAT volume, prelink Mach-O, EDK2 and DarwinBoot. Never discard known good firmware or use unrelated boot.img sizes blindly.

`flow-b` has eight register/flags-preserving one-opcode hook sites:
```
1 PROLOGUE      0xFFFFFFF0079B3424
2 TBI RETURN    0xFFFFFFF0079B3448
3 KC REBASE     0xFFFFFFF0079B3984
4 CPU DATA      0xFFFFFFF0079B39A4
5 PE PLATFORM   0xFFFFFFF0079B39B0
6 TIMER WFE     0xFFFFFFF0079B39C8
7 CPU TOPO      0xFFFFFFF0079B3A78
8 THREAD READY  0xFFFFFFF0079B3ABC
```
The additional verified zero source cave for that code is `0xFFFFFFF0073F1800..0xFFFFFFF0073F1FF0`; the tracer is 1,163 bytes, with all modified bytes bounded to the cave and eight four-byte one-opcode branches. It saves/restores x0–x18, x30 and NZCV; requires a valid kernel stack. The 8 text markers do not prove those subsystems function.

Candidate **future** sites (from previous arm64 disassembly; independently verify originals and branch layout before editing):
```
0xFFFFFFF0079B3AC8  after machine_set_current_thread
0xFFFFFFF0079B3AD0  after cpu_bootstrap
0xFFFFFFF0079B3AD4  after rtclock_early_init
0xFFFFFFF0079B3AE4  after kernel_startup_bootstrap
0xFFFFFFF0079B3AE8  after timer_call_init
0xFFFFFFF0079B3AEC  after cpu_init
0xFFFFFFF0079B3AF0  after processor_bootstrap
0xFFFFFFF0079B3B7C  after arm_vm_init
```
**These are candidate diagnostic hook sites, not already confirmed executions.** Verify symbolic names and actual instructions with the *exact* pinned Mach-O/objdump, and never interpret an entry marker as completion of the following call.

## SMP / platform reality

SM7435 Parrot DT describes eight CPUs with physical affinities `0x000,0x100,...,0x700`, four E + four P entries. A common SoC XNU reset patch was adjusted to use `MPIDR & 0xFFFF` unconditionally because an earlier `HAS_CLUSTER`-dependent fallback `MPIDR & 0xFF` would alias all eight physical IDs to zero. Source is in the SoC fork, with pin in `feeds.toml`. **Source-level change has NOT been proven in a real secondary-core launch.**

PSCI SMC and GICv3 are in device description, with GICD `0x17200000`, GICR `0x17260000`, redistributor stride `0x20000`, architectural clock 19.2 MHz. `package/Sm7435PsciReadOnly.c` compiles but is NOT executed in current boot image. `cpus=2` exists as manual opt-in only, and **NO secondary CPU has been started or validated**. Do NOT flip the default from `cpus=1` or execute CPU_ON until CPU_DATA, stack, reset vector, entry memory, PSCI conduit, GICR and per-core timer are independently checked and there is an explicit owner-approved physical test.

Recovery memory observations: 6,061 MiB vs old reference FDT 7,944 MiB, discrepancy 1,883 MiB. The old high-1GiB candidate may overlap live firmware/reserved allocations; `GetMemoryMap` at the correct handoff is needed before placing VM state or log memory. The diagnostic framebuffer reserve is 43 MiB. Android-derived DT and firmware ownership are not interchangeable.

## NEXT Work session — do the maximum safe, verified work in one pass

**Priority A — deepen single-core XNU boot beyond `8 THREAD READY`:**
1. Fetch current GitHub state + latest image SHA + hardware JSON. Verify exact Mach-O disassembly, true return addresses, branching and register conventions, locate the next calls and the last safe point prior to first failure; inspect native kernel XNU source if it matches the cache. Do not assume a particular failure or use stale README statements as facts.
2. Implement ONE high-value multi-stage `next-b` or `init-b` diagnostic extending `flow-b` beyond `_thread_bootstrap` across `machine_set_current_thread`, `cpu_bootstrap`, `rtclock_early_init`, `kernel_startup_bootstrap`, `timer_call_init`, `cpu_init`, `processor_bootstrap`, `arm_vm_init` and any actual next control-flow branch **as verified from Mach-O**. Choose safe hook sites and preserve SP, all live GPRs, NZCV, original instructions and return addresses. Prefer non-destructive, *monotonically persistent* screen messages within the verified first 2 MiB high VA GOP alias, plus bounded fault information if safe; do not overwrite UEFI memory map or vector table without verification. Check original addresses and byte limits.
3. Add valuable read-only fault/boot diagnostics where technically safe: `ESR_EL1`, `FAR_EL1`, `ELR_EL1`, `SPSR_EL1`, `VBAR_EL1`, `SP_EL1`/stack bounds, `DAIF`, `TCR/TTBR/MAIR`, boot_args pointer fields, ADT memory reservations; if an actual exception vector logger is implemented, preserve all vector entries and exception return semantics and ensure it cannot recurse. Do not print cached meaningless register values as real fault data. A minimal persistent log is OK only in explicitly validated owned memory.
4. Trace or implement actual early kernel bootstrap after the first failed subsystem, **not only infinite diagnostic markers**. For native kernel problems, prefer source-level proper fixes in the correct UniXNU/SM7435 files over hardcoding one-off binary skips; retain SHA-pinned binary instrumentation for bounded hardware evidence only.

**Priority B — enable genuine kernel progress, not paper checkmarks:**
5. Inspect `board.toml` `example=true`, OS/kernelcache compatibility, `XnuPrelink`, Apple Device Tree vs Qualcomm DT, memory map, `cpu_data`, per-CPU timer/interrupt setup, panic output, mach-o segments/slide/fixups. Determine what actually prevents a working UniXNU kernel. Create testable native build targets instead of merely flipping example=false. Make substantive compatible patches where possible.
6. Verify stable single-core exception/panic path, kernel VM initialization, processor bootstrap, scheduler and relevant IOKit/rootfs requirements in that order. Host tests/CI must distinguish compile/prelink success from boot success. Do not promise complete boot in one turn if platform integration is lacking.
7. Separately, expand a *read-only* PSCI and GICR/ADT audit with source/host tests and a potential future device probe. No PSCI CPU_ON or second-core power-up in this pass unless correct secondary trampoline/CPU_DATA and explicit user permission exist; keep `cpus=1` default. Don't borrow unverified SM8550/sheng register writes.

**Priority C — real deliverables and monitoring:**
8. Make code edits **directly in `main`** in the primary and pinned common repositories; preserve all working paths. Extend the **existing manual** `xnu-mmu-ab-lab.yml` with one new choice, not one more workflow. Leave baseline `slot-b` and tested `flow-b` selectable; no automatic push-triggered hardware experiments. Pin source and output image SHA-256, refuse mismatched inputs, include a JSON audit artifact and a single boot.img.
9. Execute all feasible local/CI tests NOW. If GitHub Actions can be manually dispatched through available authorized tools/Work browser, run the new variant, observe logs until completion, fix compilation/hashing errors and rerun until clean within the active session. If dispatch unavailable, do not falsely claim a run; give the exact click steps and expected SHA. Do not ask the owner to troubleshoot a build before exhausting CI-source checks.
10. Update **this handoff**, `data/` measurements, `CHANGELOG.md`, and concise top-level `README.md`: distinguish *hardware verified*, *CI compiled*, *locally reproduced*, *not yet tested*, *still blocked*. README had historical stale statements and is very long (~91 kB at handoff): improve concise top summary instead of prepending another long repetitive section. Preserve prior hardware evidence and old hashes for rollback.
11. End with exact GitHub commit links, successful run ID(s), release asset + SHA-256 if available, updated handoff link, what was actually fixed vs merely instrumented, remaining blockers and **ONE precise high-value next on-device `fastboot boot` test** with expected markers. If multiple non-device tasks remain feasible, complete them before ending.

**Reality check:** A completely booted UnixNU is not currently proven. It may require significant native hardware enablement and might take many iterations, not automatically two requests. Keep results falsifiable and do not simulate kernel boot or turn `8 THREAD READY` into proof of a scheduler, IRQs, SMP or userland.

**Most recent owner preference:** Ask Work to implement and test as much as possible in one run; user can return to the older GPT chat after Work, and the older chat should resume by reading THIS file plus latest `data/` and GitHub Actions, without reasking previously supplied hardware details.

Full existing workflow build step was subsequently executed locally from immutable fifth-NOSP through every predecessor to INIT-B, including FLOW-B source reproduction, emulator checks and final SHA256SUMS verification. It passed; corrupted FLOW-B input was rejected before producing output. This remains local execution, not a GitHub Actions run.

Remote publication confirmation: implementation commit [49e37866e34bfc5a9bb7b1fa61578da987bbbc5e](https://github.com/vildangil/UniXNU-Dizi-Ruan/commit/49e37866e34bfc5a9bb7b1fa61578da987bbbc5e) was pushed directly to main; git ls-remote confirmed that SHA. Working tree was clean. No Actions dispatch, release replacement or physical test was performed.

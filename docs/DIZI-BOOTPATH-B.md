# Dizi XNU: hardware-confirmed arch-b and four-stage _arm_init bootpath-b

## Hardware result — 31 October 2026

A physical Redmi Pad Pro dizi photograph shows the `arch-b`
diagnostic text:

```text
XNU ENTRY
PRE ALIAS ARMED
POST SCTLR OK
GUARD PASSED
TPIDR DONE
ARCH REGS OK
```

The [GitHub Actions run #41192216023](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/41192216023)
published a single `Mu-dizi-XNU-LATEST-TEST.img` asset with SHA-256
`58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`.
This exactly matches the independently reproduced `arch-b` output.

At the first instrumented instruction of `_arm_init`, the
compiled `arch-b` read and verified **all six guards**:

1. `MPIDR_EL1` Aff0:Aff2 = 0, main bootstrap CPU;
2. `CurrentEL = 0x4` (EL1);
3. `CNTFRQ_EL0 = 19,200,000` Hz;
4. `SCTLR_EL1.M = 1` (MMU still enabled);
5. `TPIDR_EL1 = 0`;
6. `MIDR_EL1 != 0` (processor ID register accessible).

`ARCH REGS OK` proves these predicates were true when the
instrumented code executed, **not that the body of `_arm_init`
finished** or that timer IRQs, secondary CPU entry, SecureDT,
VM allocation, UART, UFS or userland worked. The EDK2 menu
under the text is stale framebuffer contents, not a live UEFI
return. The observation is archived in
[`data/dizi-arch-b-registers-hardware-20261031.json`](../data/dizi-arch-b-registers-hardware-20261031.json).

## Next diagnostic `bootpath-b` — read-only checks beyond CPU

The **existing single manual XNU MMU A/B workflow** now offers
`bootpath-b`, which starts from the exact SHA-verified,
hardware-confirmed `arch-b` boot image. It reuses the
previous guarded MMU-on high virtual framebuffer alias and
text renderer. Rather than re-reading the six registers that
have passed, it puts four small no-SP, NZCV-neutral hooks
at native calls **inside `_arm_init`**.

| Marker shown on final row | Native hook VA | What the native code just passed |
| --- | --- | --- |
| `CPU DATA OK` | `0xFFFFFFF0079B39AC` | `_cpu_data_init` returned; next call prepares PE platform |
| `TOPO OK` | `0xFFFFFFF0079B3A5C` | `_ml_parse_cpu_topology` and `_ml_get_boot_cpu_number` returned |
| `VM SERIAL OK` | `0xFFFFFFF0079B3B98` | `_arm_vm_init`, debug inheritance, `_serial_init` returned |
| `CPU INIT OK` | `0xFFFFFFF0079B3D08` | `_cpu_timebase_init`, `_kptimer_curcpu_up`, `_PE_init_cpu` returned |

**The final row is reused at each milestone.**
For example, a photo showing `TOPO OK` means that marker was
reached, but cannot by itself establish whether the later VM
functions executed. A `CPU INIT OK` photo is the strongest
of the four outcomes. The hook at `TOPO OK` executes
**before** the next native sign/range check of the boot CPU
number; the display alone does not prove the returned
CPU index was acceptable.

The implementation restores the native `ret`,
`br x0` and `_arm_init` stack prologue from the
earlier tracer. Each new hook returns to an exact
displaced original instruction **after** rendering and
then resumes at the next native instruction. In particular,
the original store of the boot CPU number, `mov x19,x0`,
and `mov w0,#1` are replayed with the required
registers preserved. The existing guarded
`SCTLR_EL1` / `ISB`, MMU page-table construction,
native compare guard, EDK2 and boot metadata are identical
to the physically verified `arch-b` image.

Only the four one-instruction hook sites, three restored
native instructions, 156 bytes of prior diagnostic
stub space, and four fixed-width status messages differ.
219 Mach-O bytes changed. The boot was reproduced
**twice byte-for-byte** and the corresponding ARM64
branches independently disassembled.

- Source `arch-b` boot-v4 SHA-256:
  `58c612f6f09776747f2a2ccecad7e82a0fd7ee0fae632e55c5a1f56ae786772b`
- Expected `bootpath-b` boot-v4 SHA-256:
  `332debe2cb36926e389c2519ea9b877b31b596761b6f462a80479f588f6dce2d`
- Expected embedded Mach-O SHA-256:
  `b620bac2b139cbbaa1a97db7f66f67fae7223d5985d8fbd3c77394fb586243af`
- Generator: [`ci/patch_dizi_mmu_bootpath_b.py`](../ci/patch_dizi_mmu_bootpath_b.py).

### Limitations and risks

- `bootpath-b` has **not yet run on hardware**.
- It inherits the same guarded pre-MMU TTBR1 L2 framebuffer
  page-table write already hardware-confirmed by `arch-b`;
  it does **not** install any additional mappings.
- When `_arm_vm_init` executes, it may rebuild or change
  kernel translations. If the debug framebuffer alias becomes
  invalid, the following text-store can fault. Therefore a
  missing later text marker does **not** automatically mean
  the corresponding XNU function was never reached.
- No PSCI CPU_ON is performed, no secondaries run,
  no new physical MMIO is accessed, and no claim is made about
  actual UART output or timer interrupt delivery.
- Do **not** infer success merely because the EDK2 menu is
  visible below the text; the framebuffer background is stale.
- Preserve the arch-b or deep-b known-good image and Android
  recovery. Test exclusively with temporary **`fastboot boot`**;
  **never** `fastboot flash`.

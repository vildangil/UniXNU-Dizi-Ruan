/* SPDX-License-Identifier: BSD-3-Clause */
/* Optional source-only SM7435 PSCI preflight. NEVER invoked by boot image.
 * May be integrated only after a fully valid XNU EL1 calling context.
 * Arm PSCI function IDs; no CPU_ON/OFF, no MMIO or table changes. */
#include "Sm7435PsciReadOnly.h"

#if !defined(__aarch64__)
#error "Arm64 PSCI SMC only"
#endif

#define DIZI_PSCI_VERSION       UINT64_C(0x84000000)
#define DIZI_PSCI_FEATURES      UINT64_C(0x8400000A)
#define DIZI_PSCI_CPU_ON64      UINT64_C(0xC4000003)
#define DIZI_PSCI_AFFINITY64    UINT64_C(0xC4000004)

static __attribute__((noinline)) int64_t
sm7435_smc_readonly(uint64_t fid, uint64_t a1, uint64_t a2, uint64_t a3)
{
    register uint64_t x0 __asm__("x0") = fid;
    register uint64_t x1 __asm__("x1") = a1;
    register uint64_t x2 __asm__("x2") = a2;
    register uint64_t x3 __asm__("x3") = a3;
    /* SMCCC caller-saved registers; declare clobbers to prevent the compiler
     * retaining any live values across an EL3 secure monitor call. */
    __asm__ volatile("smc #0"
        : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3)
        :
        : "x4", "x5", "x6", "x7", "x8", "x9", "x10", "x11", "x12",
          "x13", "x14", "x15", "x16", "x17", "memory", "cc");
    return (int64_t)x0;
}

void
dizi_sm7435_psci_readonly_snapshot(struct dizi_sm7435_psci_snapshot *out)
{
    if (!out) return;
    uint64_t mpidr;
    __asm__ volatile("mrs %0, MPIDR_EL1" : "=r"(mpidr));
    out->bootstrap_mpidr = mpidr;
    out->psci_version = sm7435_smc_readonly(DIZI_PSCI_VERSION, 0, 0, 0);
    out->cpu_on_feature = sm7435_smc_readonly(DIZI_PSCI_FEATURES, DIZI_PSCI_CPU_ON64, 0, 0);
    for (unsigned int logical = 0; logical < DIZI_SM7435_CPU_COUNT; ++logical) {
        const uint64_t physical_affinity = (uint64_t)logical << 8;
        out->affinity_info[logical] = sm7435_smc_readonly(
            DIZI_PSCI_AFFINITY64, physical_affinity, 0, 0);
    }
}

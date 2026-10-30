/* SPDX-License-Identifier: BSD-3-Clause */
#ifndef DIZI_SM7435_PSCI_READONLY_H
#define DIZI_SM7435_PSCI_READONLY_H
#include <stdint.h>
#define DIZI_SM7435_CPU_COUNT 8
struct dizi_sm7435_psci_snapshot {
    uint64_t bootstrap_mpidr;
    int64_t psci_version;
    int64_t cpu_on_feature;
    int64_t affinity_info[DIZI_SM7435_CPU_COUNT];
};
/* PSCI query functions ONLY. No CPU_ON/OFF; caller provides mapped memory.
 * Must be called only after EL1/SMC access and a valid stack are verified.
 * Does not register XNU secondary CPUs or touch GIC/clock MMIO. */
void dizi_sm7435_psci_readonly_snapshot(struct dizi_sm7435_psci_snapshot *out);
#endif

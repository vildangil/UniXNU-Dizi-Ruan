// SPDX-License-Identifier: BSD-2-Clause-Patent
// RuanWifiProbe: Qualcomm WCN6750 Wi-Fi (icnss2 / ath11k) hardware probe & MSA management for ruan.
#ifndef RUAN_WIFI_PROBE_H
#define RUAN_WIFI_PROBE_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define WCN6750_MSI_ADDR            0x17210040ULL
#define WCN6750_SMMU_IOVA_IPA       0xB0000000ULL
#define WCN6750_SMMU_IOVA_IPA_SIZE  0x00010000ULL  /* 64 KiB */
#define WCN6750_MSA_PHYS            0x82A00000ULL
#define WCN6750_MSA_SIZE            0x00C00000ULL  /* 12 MiB */

struct ruan_wifi_telemetry {
    int probed;
    int msa_verified;
    uint64_t msi_addr;
    uint64_t msa_phys;
    uint32_t msa_size;
    char status[64];
};

extern struct ruan_wifi_telemetry g_ruan_wifi;

void ruan_wifi_init(void);
const char *ruan_wifi_status_str(void);

#ifdef __cplusplus
}
#endif

#endif // RUAN_WIFI_PROBE_H

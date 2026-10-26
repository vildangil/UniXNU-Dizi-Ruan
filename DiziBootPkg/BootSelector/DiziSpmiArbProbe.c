/** @file
  Safe stage-1 hardware visibility for SM7435/dizi SPMI Arbiter:
    core:   0x0c400000 length 0x3000 (board DT)
    cnfg:   0x0c42d000 length 0x4000
    chnls:  0x0c500000, obsrvr: 0x0c440000
  The pinned Mu-Silicium dizi MemoryMapLib maps the entire AOSS
  0x0b000000..0x0effffff region as NS_DEVICE. This probe reads ONLY
  core VERSION, per-bus FEATURES, and the static PPID-to-APID mapping table.
  It never issues an SPMI command, writes MMIO, reconfigures IRQs,
  installs a fake protocol, or writes a PMIC register.

  The version-specific APID map offsets come from upstream Linux's
  drivers/spmi/spmi-pmic-arb.c. Unsupported revisions fail closed.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/BaseMemoryLib.h>
#include <Library/IoLib.h>
#include "DiziSpmiArbProbe.h"

#define DIZI_ARB_CORE_BASE      0x0c400000U
#define DIZI_ARB_CORE_BYTES     0x00003000U
#define DIZI_ARB_VERSION_REG    0x0000U
#define DIZI_ARB_FEATURES_REG   0x0004U
#define DIZI_ARB_V5_MAP_OFFSET  0x0900U
#define DIZI_ARB_V7_MAP_OFFSET  0x2000U
#define DIZI_ARB_PPID_PON       0x0013U   // PMK8350 SID 0 / PON 0x13
#define DIZI_ARB_PPID_GPIO1     0x0188U   // PM6450 SID 1 / GPIO 0x88
#define DIZI_ARB_PPID_MASK      0x0fffU
#define DIZI_ARB_APID_FEATURES  0x07ffU
#define DIZI_ARB_MAX_APIDS_V5   512U
#define DIZI_ARB_MAX_APIDS_V7   1024U

VOID
DiziProbeSpmiArbiterReadOnly (OUT DIZI_SPMI_ARB_PROBE *Result)
{
  UINT32 Offset, MaxApids, Count, Index, Mapping, Ppid, Shift;
  if (Result == NULL) return;
  ZeroMem (Result, sizeof(*Result));

  // SPMI controller is inside the board's existing AOSS device mapping.
  Result->Version = MmioRead32 (DIZI_ARB_CORE_BASE + DIZI_ARB_VERSION_REG);
  // Qualcomm PMIC_ARB_VERSION encodes major revision in bits [31:28].
  // Example: actual dizi 0x70000000 => v7, not 0x70.
  // Compare Linux PMIC_ARB_VERSION_V7_MIN (0x70000000).
  switch (Result->Version >> 28U) {
    case 5U:
      Offset = DIZI_ARB_V5_MAP_OFFSET;
      MaxApids = DIZI_ARB_MAX_APIDS_V5;
      break;
    case 7U:
      Offset = DIZI_ARB_V7_MAP_OFFSET;
      MaxApids = DIZI_ARB_MAX_APIDS_V7;
      break;
    default:
      // Do not read further unknown register layouts.
      Result->Completed = TRUE;
      return;
  }
  Result->VersionSupported = TRUE;
  Result->Features = MmioRead32 (DIZI_ARB_CORE_BASE + DIZI_ARB_FEATURES_REG);
  Result->Bus0Apids = Result->Features & DIZI_ARB_APID_FEATURES;
  if ((Result->Version >> 28U) == 7U) {
    // On SPMI Arbiter v7 the second bus has its own FEATURES register.
    // Linux _pmic_arb_init_apid_v7 computes bus1 base = bus0 APID count.
    // Read both even if bus0 is zero: this is read-only discovery.
    Result->FeaturesBus1 = MmioRead32 (DIZI_ARB_CORE_BASE +
                                        DIZI_ARB_FEATURES_REG + 4U);
    Result->Bus1Apids = Result->FeaturesBus1 & DIZI_ARB_APID_FEATURES;
  }
  Count = Result->Bus0Apids + Result->Bus1Apids;
  Result->ApidCount = Count;
  // v7 diagnostic only: if both bus FEATURES counters are zero,
  // sample four fixed entries at the *documented* v7 APID map window.
  // All sample offsets lie inside the dizi 0x3000-byte core MMIO area.
  // Do not infer ownership or drive a transaction from these values.
  // In particular, sampling is NOT a substitute for a valid APID count.
  if ((Result->Version >> 28U) == 7U && Count == 0 &&
      Offset == DIZI_ARB_V7_MAP_OFFSET &&
      (Offset + 4U * 129U) <= DIZI_ARB_CORE_BYTES) {
    Result->MapSample0   = MmioRead32 (DIZI_ARB_CORE_BASE + Offset);
    Result->MapSample1   = MmioRead32 (DIZI_ARB_CORE_BASE + Offset + 4U);
    Result->MapSample16  = MmioRead32 (DIZI_ARB_CORE_BASE + Offset + 64U);
    Result->MapSample128 = MmioRead32 (DIZI_ARB_CORE_BASE + Offset + 512U);
    Result->MapSamplesValid = TRUE;
  }

  // Do not scan speculative APIDs if firmware advertises zero or an
  // out-of-bounds count. The v7 MMIO mapping is only 0x1000 bytes long.
  if (Count == 0 || Count > MaxApids ||
      Offset > DIZI_ARB_CORE_BYTES ||
      Count > (DIZI_ARB_CORE_BYTES - Offset) / sizeof (UINT32)) {
    Result->Completed = TRUE;
    return;
  }
  Shift = 8U; // v5/v7 map format: PPID in bits 8..19, IRQ owner in bit24.
  for (Index = 0; Index < Count; ++Index) {
    Mapping = MmioRead32 (DIZI_ARB_CORE_BASE + Offset +
                          Index * sizeof (UINT32));
    if (Mapping == 0) continue;
    Ppid = (Mapping >> Shift) & DIZI_ARB_PPID_MASK;
    if (Ppid == DIZI_ARB_PPID_PON) {
      Result->PonMapped = TRUE;
      Result->PonApid = Index;
    }
    if (Ppid == DIZI_ARB_PPID_GPIO1) {
      Result->GpioMapped = TRUE;
      Result->GpioApid = Index;
    }
  }
  Result->MapsReadable = TRUE;
  Result->Completed = TRUE;
}

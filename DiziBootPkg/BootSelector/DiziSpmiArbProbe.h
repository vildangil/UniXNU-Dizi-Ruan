/** @file
  DIZI board-specific, register-read-only PMIC Arbiter discovery.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#ifndef DIZI_SPMI_ARB_PROBE_H
#define DIZI_SPMI_ARB_PROBE_H
#include <Uefi.h>
typedef struct {
  BOOLEAN Completed;
  BOOLEAN VersionSupported;
  BOOLEAN MapsReadable;
  BOOLEAN PonMapped;
  BOOLEAN GpioMapped;
  UINT32 Version;
  UINT32 Features;
  UINT32 FeaturesBus1;
  UINT32 Bus0Apids;
  UINT32 Bus1Apids;
  // Raw, read-only samples from the documented v7 APID->PPID table.
  // These do not imply valid channels if FEATURES reports zero.
  BOOLEAN MapSamplesValid;
  UINT32 MapSample0;
  UINT32 MapSample1;
  UINT32 MapSample16;
  UINT32 MapSample128;
  UINT32 ApidCount;
  UINT32 PonApid;
  UINT32 GpioApid;
} DIZI_SPMI_ARB_PROBE;

VOID DiziProbeSpmiArbiterReadOnly (OUT DIZI_SPMI_ARB_PROBE *Result);
// Return 0 on successful approved one-byte register READ, else error code.
UINT32 DiziArbReadKeyRegister (IN CONST DIZI_SPMI_ARB_PROBE *Arb,
                               IN UINT32 Sid, IN UINT32 Register,
                               OUT UINT8 *Value);
#endif

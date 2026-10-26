/** @file
  DIZI PMIC button polling through *existing* Qualcomm EFI SPMI ReadLong.
  Does not install PMIC protocols or touch register writes.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#ifndef DIZI_PMIC_KEYS_H
#define DIZI_PMIC_KEYS_H
#include <Uefi.h>
#include <Protocol/SimpleTextIn.h>
#include "DiziSpmiArbProbe.h"
typedef struct {
  BOOLEAN SpmiAvailable;
  BOOLEAN ArbiterAvailable;
  BOOLEAN PonValid;
  BOOLEAN GpioValid;
  BOOLEAN PowerDown;
  BOOLEAN VolDown;
  BOOLEAN VolUp;
  UINT8 PonRaw;
  UINT8 GpioRaw;
  UINT32 PonResult;
  UINT32 GpioResult;
  UINT32 ReadFailures;
  UINT8 Stable;
  UINT8 Candidate;
  UINT8 Consecutive;
  BOOLEAN Initialized;
  UINT32 NextSearchTick;
  VOID *Spmi;
} DIZI_PMIC_KEYS;
VOID DiziPmicSampleKeys (IN OUT DIZI_PMIC_KEYS *Keys, IN CONST DIZI_SPMI_ARB_PROBE *Arb,
                         IN UINT32 Tick,
                         OUT EFI_INPUT_KEY *NewPress, OUT BOOLEAN *Pressed);
#endif

/** @file
  DIZI PMIC button registers: bounded SPMI Arbiter v7 *READ* command.
  This file may write ONLY the observer channel CMD register to launch
  SPMI_EXT_READL (opcode 1), never PMIC data, clock, reset, mode, IRQ or
  bus-owner registers. Experimental temporary fastboot boot ONLY.

  dizi.dts: qcom,ee=0; core=0x0c400000; obsrvr=0x0c440000.
  Linux spmi-pmic-arb.c: v7 observer offset 0x8000*ee+0x20*apid.
  No borrowed SPMIDxe, and no protocol installation.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/IoLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include "DiziSpmiArbProbe.h"

#define DIZI_OBSERVER_BASE 0x0c440000U
#define DIZI_OBSERVER_BYTES 0x00080000U
#define DIZI_OBSERVER_STRIDE 0x20U
#define DIZI_SPMI_CORE_BASE 0x0c400000U
#define DIZI_SPMI_V7_APID_MAP 0x2000U
#define DIZI_SPMI_CMD 0x00U
#define DIZI_SPMI_STATUS 0x08U
#define DIZI_SPMI_RDATA0 0x18U
#define DIZI_SPMI_OP_EXT_READL 1U
#define DIZI_SPMI_TIMEOUT_US 1000U
#define DIZI_PON_REG 0x1310U
#define DIZI_VOLUP_REG 0x8808U

UINT32
DiziArbReadKeyRegister (
  IN CONST DIZI_SPMI_ARB_PROBE *Arb,
  IN UINT32 Sid,
  IN UINT32 Register,
  OUT UINT8 *Value
  )
{
  UINT32 Apid, Ppid, Mapping, Offset, Cmd, Status;
  UINT32 Poll;

  if (Value == NULL || Arb == NULL) return 1U;
  *Value = 0;
  // v7 ONLY, both mappings must have come from a bounded scan of the
  // genuine hardware APID table; bus 0 is the only verified HLOS bus.
  if (Arb->Version < 0x70000000U || Arb->Version >= 0x80000000U ||
      !Arb->MapsReadable || Arb->ApidCount == 0 ||
      Arb->ApidCount > 1024U || Arb->Bus0Apids == 0)
    return 2U;
  if (Sid == 0U && Register == DIZI_PON_REG && Arb->PonMapped) {
    Apid = Arb->PonApid;
    Ppid = 0x0013U;
  } else if (Sid == 1U && Register == DIZI_VOLUP_REG &&
             Arb->GpioMapped) {
    Apid = Arb->GpioApid;
    Ppid = 0x0188U;
  } else return 3U;
  if (Apid >= Arb->Bus0Apids || Apid >= 1024U) return 4U;

  // Revalidate the actual PPID to prevent accidental transactions to an
  // unrelated channel if a boot stage altered controller configuration.
  Mapping = MmioRead32 (DIZI_SPMI_CORE_BASE +
                        DIZI_SPMI_V7_APID_MAP + 4U * Apid);
  if (Mapping == 0 || ((Mapping >> 8U) & 0x0fffU) != Ppid)
    return 5U;
  Offset = DIZI_OBSERVER_STRIDE * Apid;
  if (Offset + DIZI_SPMI_RDATA0 + sizeof(UINT32) > DIZI_OBSERVER_BYTES)
    return 6U;

  // EXT_READL byte count 1 (encoded 0). This writes a READ *command*
  // only to the observer CMD register, not a value into the PMIC.
  Cmd = (DIZI_SPMI_OP_EXT_READL << 27U) |
        ((Register & 0xffU) << 4U);
  MmioWrite32 (DIZI_OBSERVER_BASE + Offset + DIZI_SPMI_CMD, Cmd);
  for (Poll = 0; Poll < DIZI_SPMI_TIMEOUT_US; ++Poll) {
    Status = MmioRead32 (DIZI_OBSERVER_BASE +
                         Offset + DIZI_SPMI_STATUS);
    if ((Status & 1U) != 0) {
      // Linux PMIC_ARB v7 status bits 1=FAIL, 2=DENIED, 3=DROPPED.
      if ((Status & 0x0eU) != 0) return 0x10U | (Status & 0x0eU);
      *Value = (UINT8)MmioRead32 (DIZI_OBSERVER_BASE +
                                   Offset + DIZI_SPMI_RDATA0);
      return 0U;
    }
    gBS->Stall (1U);
  }
  return 0x20U; // Timed out; do not retry indefinitely.
}

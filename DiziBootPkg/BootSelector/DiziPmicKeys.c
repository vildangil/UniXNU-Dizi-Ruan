/** @file
  Board-based, read-only Qualcomm PMIC key fallback for dizi (SM7435).
  Verified board DT: PMK8350 SID0 PON@1300 (power, RESIN/volume-down),
  PM6450 SID1 GPIO1@8800 (volume-up active-low).
  PMK8350 GEN3 PON RT_STS 0x10: KPDPWR bit7, RESIN bit6.\n  PM6450 GPIO STATUS 0x08 bit0 is active low. Based on Linux\n  pm8941-pwrkey.c (qcom,pmk8350-pwrkey / pmk8350-resin).
  Uses installed Qualcomm SPMI UEFI protocol when present; otherwise
  performs strictly bounded observer-channel SPMI READ commands through the
  verified dizi SPMI Arbiter v7. Never installs fake protocols, writes PMIC
  registers, or changes GPIO/Type-C configuration.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Protocol/SimpleTextIn.h>
#include <Library/UefiBootServicesTableLib.h>
#include "DiziPmicKeys.h"

STATIC EFI_GUID mDiziSpmiGuid = {
  0xfa5f306b, 0xf47d, 0x4ac4, {0xa4,0x7d,0x88,0x2f,0x82,0x04,0xec,0x30}
};

// ABI from Qualcomm EFISPMI.h, 2019; only Revision and ReadLong used.
// Spmi_Result and Spmi_AccessPriority are 32-bit enums in Qualcomm headers.
typedef struct _DIZI_SPMI DIZI_SPMI;
typedef INT32 (EFIAPI *DIZI_SPMI_READLONG)(
  DIZI_SPMI *This, UINT32 Slave, UINT32 Priority, UINT32 Address,
  UINT8 *Data, UINT32 Length, UINT32 *ReadBytes);
struct _DIZI_SPMI {
  UINT64 Revision;
  DIZI_SPMI_READLONG ReadLong;
};
#define DIZI_SPMI_REVISION 0x0000000000010001ULL
#define DIZI_SPMI_OK 0
#define DIZI_PON_RT_STS 0x1310U
#define DIZI_GPIO1_STATUS 0x8808U
#define DIZI_PON_GEN3_POWER_MASK 0x80U
#define DIZI_PON_GEN3_RESIN_MASK 0x40U

STATIC
BOOLEAN
ReadOne (DIZI_SPMI *Spmi, UINT32 Sid, UINT32 Register,
         OUT UINT8 *Value, OUT UINT32 *Error)
{
  UINT32 Bytes = 0;
  INT32 Result;
  *Value = 0;
  if (Spmi == NULL || Spmi->ReadLong == NULL) {
    *Error = MAX_UINT32;
    return FALSE;
  }
  // SPMI_ACCESS_PRIORITY_LOW=0. A read, not ReadModifyWriteLongByte.
  Result = Spmi->ReadLong (Spmi, Sid, 0, Register, Value, 1, &Bytes);
  *Error = (UINT32)Result;
  return Result == DIZI_SPMI_OK && Bytes == 1;
}

VOID
DiziPmicSampleKeys (
  IN OUT DIZI_PMIC_KEYS *Keys,
  IN CONST DIZI_SPMI_ARB_PROBE *Arb,
  IN UINT32 Tick,
  OUT EFI_INPUT_KEY *NewPress,
  OUT BOOLEAN *Pressed
  )
{
  EFI_STATUS Status;
  DIZI_SPMI *Spmi;
  UINT8 RawPon = 0, RawGpio = 0, Raw = 0;
  BOOLEAN ValidPon, ValidGpio;
  UINT8 NewlyPressed;

  if (Pressed == NULL || NewPress == NULL || Keys == NULL) return;
  *Pressed = FALSE;
  NewPress->ScanCode = SCAN_NULL;
  NewPress->UnicodeChar = 0;
  // Bound bus work to <=10Hz even though the menu tick is 20Hz.
  if ((Tick & 1U) != 0) return;

  Spmi = (DIZI_SPMI *)Keys->Spmi;
  if (Spmi == NULL && Tick >= Keys->NextSearchTick) {
    Keys->NextSearchTick = Tick + 20U;
    Status = gBS->LocateProtocol (&mDiziSpmiGuid, NULL, (VOID **)&Spmi);
    if (EFI_ERROR (Status) || Spmi == NULL ||
        Spmi->Revision != DIZI_SPMI_REVISION || Spmi->ReadLong == NULL) {
      Spmi = NULL;
      Keys->SpmiAvailable = FALSE;
    } else {
      Keys->Spmi = Spmi;
      Keys->SpmiAvailable = TRUE;
    }
  }

  // Fail closed after six bad samples. Never write PMIC data registers.
  if (Keys->ReadFailures >= 6) return;
  if (Spmi != NULL) {
    ValidPon = ReadOne (Spmi, 0, DIZI_PON_RT_STS, &RawPon,
                        &Keys->PonResult);
    ValidGpio = ReadOne (Spmi, 1, DIZI_GPIO1_STATUS, &RawGpio,
                         &Keys->GpioResult);
  } else if (Arb != NULL && Arb->MapsReadable && Arb->PonMapped &&
             Arb->GpioMapped) {
    // Only the MMIO command register is written to dispatch SPMI READL.
    // DiziArbReadKeyRegister validates the APID and allowed address.
    Keys->PonResult = DiziArbReadKeyRegister (Arb, 0, DIZI_PON_RT_STS,
                                               &RawPon);
    Keys->GpioResult = DiziArbReadKeyRegister (Arb, 1,
                                                DIZI_GPIO1_STATUS,
                                                &RawGpio);
    ValidPon = Keys->PonResult == 0U;
    ValidGpio = Keys->GpioResult == 0U;
    Keys->ArbiterAvailable = ValidPon && ValidGpio;
  } else {
    return;
  }
  Keys->PonValid = ValidPon;
  Keys->GpioValid = ValidGpio;
  if (!ValidPon || !ValidGpio) {
    ++Keys->ReadFailures;
    return;
  }

  Keys->PonRaw = RawPon;
  Keys->GpioRaw = RawGpio;
  // PMK8350 GEN3 exposes KPDPWR at bit7 and RESIN at bit6,
  // unlike the older PM8941 PON status register (bits0/1).
  Keys->PowerDown = (RawPon & DIZI_PON_GEN3_POWER_MASK) != 0;
  Keys->VolDown = (RawPon & DIZI_PON_GEN3_RESIN_MASK) != 0;
  Keys->VolUp = (RawGpio & 0x01U) == 0;
  Raw = (Keys->VolUp ? 1U : 0U) |
        (Keys->VolDown ? 2U : 0U) |
        (Keys->PowerDown ? 4U : 0U);
  if (!Keys->Initialized) {
    // Ignore keys held while arriving from bootloader. Only new press edges
    // after the first valid sample should navigate/select the menu.
    Keys->Initialized = TRUE;
    Keys->Stable = Raw;
    Keys->Candidate = Raw;
    Keys->Consecutive = 0;
    return;
  }

  if (Raw != Keys->Candidate) {
    Keys->Candidate = Raw;
    Keys->Consecutive = 1;
    return;
  }
  if (Keys->Consecutive < 2) ++Keys->Consecutive;
  if (Keys->Consecutive < 2 || Keys->Stable == Keys->Candidate) return;

  NewlyPressed = (UINT8)(Keys->Candidate & ~Keys->Stable);
  Keys->Stable = Keys->Candidate;
  if ((NewlyPressed & 1U) != 0) NewPress->ScanCode = SCAN_UP;
  else if ((NewlyPressed & 2U) != 0) NewPress->ScanCode = SCAN_DOWN;
  else if ((NewlyPressed & 4U) != 0) NewPress->ScanCode = SCAN_SUSPEND;
  else return;
  *Pressed = TRUE;
}

/** @file
  Large, single-screen DIZI status panel using UEFI GOP Blt only.
  Safe fallback to the firmware text console if GOP is absent.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#ifndef DIZI_SCALED_UI_H
#define DIZI_SCALED_UI_H
#include <Uefi.h>
BOOLEAN DiziDrawScaledUi (CONST CHAR8 *CONST *Lines, UINTN LineCount);
#endif

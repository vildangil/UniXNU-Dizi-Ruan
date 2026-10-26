/** @file
  Pixel-scaled 5x7 ASCII status panel. No MMIO, framebuffer address access,
  graphics mode change or font protocol dependency. One GOP Blt per redraw.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Protocol/GraphicsOutput.h>
#include "DiziScaledUi.h"

#define PANEL_COLS 46U
#define PANEL_ROWS 15U
#define MAX_SCALE 4U

typedef struct {
  CHAR8 Letter;
  UINT8 Rows[7];
} DIZI_GLYPH;

// Minimal embedded glyphs: output is uppercase ASCII by design.
STATIC CONST UINT8 mUnknownGlyph[7] = {14,17,1,2,4,0,4};
STATIC CONST DIZI_GLYPH mGlyphs[] = {
  {'A',{14,17,17,31,17,17,17}}, {'B',{30,17,17,30,17,17,30}},
  {'C',{14,17,16,16,16,17,14}}, {'D',{30,17,17,17,17,17,30}},
  {'E',{31,16,16,30,16,16,31}}, {'F',{31,16,16,30,16,16,16}},
  {'G',{14,17,16,23,17,17,14}}, {'H',{17,17,17,31,17,17,17}},
  {'I',{31,4,4,4,4,4,31}},      {'J',{7,2,2,2,18,18,12}},
  {'K',{17,18,20,24,20,18,17}}, {'L',{16,16,16,16,16,16,31}},
  {'M',{17,27,21,21,17,17,17}}, {'N',{17,25,21,19,17,17,17}},
  {'O',{14,17,17,17,17,17,14}}, {'P',{30,17,17,30,16,16,16}},
  {'Q',{14,17,17,17,21,18,13}}, {'R',{30,17,17,30,20,18,17}},
  {'S',{15,16,16,14,1,1,30}},  {'T',{31,4,4,4,4,4,4}},
  {'U',{17,17,17,17,17,17,14}}, {'V',{17,17,17,17,17,10,4}},
  {'W',{17,17,17,21,21,21,10}}, {'X',{17,17,10,4,10,17,17}},
  {'Y',{17,17,10,4,4,4,4}},    {'Z',{31,1,2,4,8,16,31}},
  {'0',{14,17,19,21,25,17,14}}, {'1',{4,12,4,4,4,4,14}},
  {'2',{14,17,1,2,4,8,31}},   {'3',{30,1,1,14,1,1,30}},
  {'4',{2,6,10,18,31,2,2}},   {'5',{31,16,16,30,1,1,30}},
  {'6',{14,16,16,30,17,17,14}}, {'7',{31,1,2,4,8,8,8}},
  {'8',{14,17,17,14,17,17,14}}, {'9',{14,17,17,15,1,1,14}},
  {' ',{0,0,0,0,0,0,0}},      {':',{0,4,4,0,4,4,0}},
  {'-',{0,0,0,31,0,0,0}},     {'.',{0,0,0,0,0,12,12}},
  {'/',{1,1,2,4,8,16,16}},   {'>',{16,8,4,2,4,8,16}},
  {'[',{14,8,8,8,8,8,14}},    {']',{14,2,2,2,2,2,14}},
  {'(',{2,4,8,8,8,4,2}},     {')',{8,4,2,2,2,4,8}},
  {'=',{0,0,31,0,31,0,0}},    {'?',{14,17,1,2,4,0,4}},
  {'_',{0,0,0,0,0,0,31}},     {'+', {0,4,4,31,4,4,0}},
  {'|',{4,4,4,4,4,4,4}},     {'#',{10,10,31,10,31,10,10}}
};

STATIC EFI_GRAPHICS_OUTPUT_PROTOCOL *mGop = NULL;
STATIC EFI_GRAPHICS_OUTPUT_BLT_PIXEL *mCanvas = NULL;
STATIC UINTN mPanelWidth = 0;
STATIC UINTN mPanelHeight = 0;
STATIC UINTN mScale = 0;
STATIC BOOLEAN mGopUnavailable = FALSE;
STATIC BOOLEAN mFirstFrame = TRUE;

STATIC
CONST UINT8 *
GlyphFor (CHAR8 C)
{
  UINTN I;
  if (C >= 'a' && C <= 'z') C = (CHAR8)(C - 'a' + 'A');
  for (I = 0; I < sizeof(mGlyphs)/sizeof(mGlyphs[0]); ++I) {
    if (mGlyphs[I].Letter == C) return mGlyphs[I].Rows;
  }
  // An unknown symbol renders as a question mark, never as garbage.
  return mUnknownGlyph;
}

STATIC
VOID
PutPixel (UINTN X, UINTN Y, UINT8 R, UINT8 G, UINT8 B)
{
  EFI_GRAPHICS_OUTPUT_BLT_PIXEL *P;
  if (X >= mPanelWidth || Y >= mPanelHeight) return;
  P = &mCanvas[Y * mPanelWidth + X];
  P->Red = R; P->Green = G; P->Blue = B; P->Reserved = 0;
}

STATIC
VOID
DrawChar (UINTN X, UINTN Y, CHAR8 C, UINT8 Brightness)
{
  CONST UINT8 *Rows = GlyphFor (C);
  UINTN Row, Col, SX, SY;
  for (Row = 0; Row < 7; ++Row) {
    for (Col = 0; Col < 5; ++Col) {
      if ((Rows[Row] & (1U << (4U - Col))) == 0) continue;
      for (SY = 0; SY < mScale; ++SY)
        for (SX = 0; SX < mScale; ++SX)
          PutPixel (X + Col*mScale + SX, Y + Row*mScale + SY,
                    Brightness, Brightness, Brightness);
    }
  }
}

BOOLEAN
DiziDrawScaledUi (CONST CHAR8 *CONST *Lines, UINTN LineCount)
{
  UINTN W, H, AllowedW, AllowedH, Scale, X, Y, I, J;
  EFI_STATUS Status;

  if (mGopUnavailable || Lines == NULL || LineCount > PANEL_ROWS) return FALSE;
  if (mGop == NULL) {
    Status = gBS->LocateProtocol (&gEfiGraphicsOutputProtocolGuid,
                                  NULL, (VOID **)&mGop);
    if (EFI_ERROR (Status) || mGop == NULL || mGop->Mode == NULL ||
        mGop->Mode->Info == NULL || mGop->Blt == NULL) {
      mGopUnavailable = TRUE;
      return FALSE;
    }
  }

  W = mGop->Mode->Info->HorizontalResolution;
  H = mGop->Mode->Info->VerticalResolution;
  if (W < 600 || H < 400) return FALSE;
  AllowedW = W / ((PANEL_COLS + 4U)*6U);
  AllowedH = H / ((PANEL_ROWS + 2U)*10U);
  Scale = (AllowedW < AllowedH) ? AllowedW : AllowedH;
  if (Scale > MAX_SCALE) Scale = MAX_SCALE;
  if (Scale == 0) return FALSE;
  if (mCanvas == NULL) {
    mScale = Scale;
    mPanelWidth = (PANEL_COLS + 4U)*6U*Scale;
    mPanelHeight = (PANEL_ROWS + 2U)*10U*Scale;
    if (mPanelWidth > MAX_UINTN / mPanelHeight ||
        mPanelWidth*mPanelHeight > MAX_UINTN / sizeof(*mCanvas))
      return FALSE;
    mCanvas = AllocatePool (mPanelWidth*mPanelHeight*sizeof(*mCanvas));
    if (mCanvas == NULL) return FALSE;
  } else if (Scale != mScale) {
    // No mode changes are expected during the diagnostic selector.
    return FALSE;
  }

  for (I = 0; I < mPanelWidth*mPanelHeight; ++I) {
    mCanvas[I].Blue = 18;
    mCanvas[I].Green = 18;
    mCanvas[I].Red = 18;
    mCanvas[I].Reserved = 0;
  }

  // Thin rectangle around the centered panel; no hardware register access.
  for (X = 0; X < mPanelWidth; ++X) {
    PutPixel (X, 0, 104, 104, 104);
    PutPixel (X, mPanelHeight-1, 104, 104, 104);
  }
  for (Y = 0; Y < mPanelHeight; ++Y) {
    PutPixel (0, Y, 104, 104, 104);
    PutPixel (mPanelWidth-1, Y, 104, 104, 104);
  }

  for (I = 0; I < LineCount; ++I) {
    if (Lines[I] == NULL) continue;
    for (J = 0; Lines[I][J] != 0 && J < PANEL_COLS; ++J) {
      DrawChar ((2U*6U + J*6U)*mScale,
                (I + 1U)*10U*mScale,
                Lines[I][J], (Lines[I][0] == '>') ? 255 : 218);
    }
  }

  if (mFirstFrame) {
    // ConOut is initialized and already confirmed working on DIZI.
    // Clearing it does not alter GOP mode or destroy the fallback path.
    EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *TextOut = gST->ConOut;
    if (TextOut != NULL) TextOut->ClearScreen (TextOut);
    mFirstFrame = FALSE;
  }

  Status = mGop->Blt (mGop, mCanvas, EfiBltBufferToVideo, 0, 0,
                     (W - mPanelWidth)/2U, (H - mPanelHeight)/2U,
                     mPanelWidth, mPanelHeight, mPanelWidth*sizeof(*mCanvas));
  if (EFI_ERROR (Status)) {
    mGopUnavailable = TRUE;
    return FALSE;
  }
  return TRUE;
}

/** @file
  DIZI boot selector with direct Qualcomm keypad and console keyboard polling.
  Input is diagnostic: unsupported Power scan codes are shown, not guessed.
  No writes to Android partitions, NVRAM or firmware.
  SPDX-License-Identifier: BSD-2-Clause-Patent
**/
#include <Uefi.h>
#include <Library/BaseLib.h>
#include <Library/BaseMemoryLib.h>
#include <Library/DevicePathLib.h>
#include <Library/MemoryAllocationLib.h>
#include <Library/UefiBootServicesTableLib.h>
#include <Library/UefiLib.h>
#include <Library/PrintLib.h>
#include "DiziScaledUi.h"
#include "DiziPmicKeys.h"
#include "DiziSpmiArbProbe.h"

// Replaced at build time by the Arch workflow. Never reuse an unverified
// image from an older diagnostic run: the current ID is visible in the UI.
#define DIZI_BUILD_STAMP "R3-UNSTAMPED"
#include <Protocol/DevicePath.h>
#include <Protocol/SimpleTextInEx.h>
#include <Protocol/SimpleTextIn.h>
#include <Protocol/SimpleFileSystem.h>
#include <Protocol/Usb2HostController.h>
#include <Protocol/UsbIo.h>
#include <Protocol/PciIo.h>
#include <Protocol/PciRootBridgeIo.h>
#include <Protocol/LoadedImage.h>
#include <Protocol/DriverBinding.h>
#include <Pi/PiFirmwareFile.h>
#include <Pi/PiFirmwareVolume.h>
#include <Protocol/FirmwareVolume2.h>

#define ANDROID_LOADER L"\\EFI\\DIZI\\ANDROIDAA64.EFI"
#define DARWIN_LOADER  L"\\EFI\\DIZI\\XNUAA64.EFI"
// UniXNU.efi (UEFI_APPLICATION) FILE_GUID from upstream UniXNUPkg.
STATIC EFI_GUID mUniXnuFileGuid =
  { 0x9B665204, 0xA133, 0x47A2, { 0x93, 0x96, 0x9E, 0x2B, 0x37, 0x0A, 0x4E, 0x25 } };
#define TIMEOUT_TICKS 1200  // 60s idle timeout (50ms per timer tick)
#define TICK_100NS 500000ULL

// Device path of Qualcomm ButtonsDxe, also used by upstream BootManagerLib.
STATIC CONST EFI_GUID mKeypadGuid =
  { 0xd7f58a0e, 0xbed2, 0x4b5a, { 0xbb, 0x43, 0x8a, 0xb2, 0x3d, 0xd0, 0xe2, 0xb0 } };

// Qualcomm public PMIC PON protocol GUID from QcomPkg/Protocol/EFIPmicPon.h.
// Read-only LocateHandleBuffer only. No SPMI transactions or regulator writes.
STATIC EFI_GUID mPmicPonProtocolGuid =
  { 0x97044b58, 0xfea4, 0x4ad0, { 0x9d, 0x0b, 0xe4, 0x17, 0xd6, 0x0f, 0x11, 0xa1 } };
// These two are DIFFERENT Qualcomm PMIC APIs. ButtonsDxe requires BOTH
// exact GUIDs as proven by its on-disk DXE_DEPEX, not the PON GUID above.
STATIC EFI_GUID mPmicGpioProtocolGuid =
  { 0x4bc5c6d7, 0x4ca4, 0x8835, { 0xd1, 0xbc, 0xd2, 0x9c, 0xc2, 0x02, 0x5d, 0x4a } };
STATIC EFI_GUID mPmicPwrOnProtocolGuid =
  { 0x9ba45b66, 0xefa4, 0x441c, { 0xa3, 0xe4, 0xed, 0x22, 0x24, 0x78, 0x6b, 0xe2 } };
// Qualcomm USB configuration is the INPUT of XhciPciEmulationDxe,
// not a PCI result. Count vendor protocol providers, no function calls.
STATIC EFI_GUID mDiziUsbConfigProtocolGuid =
  { 0xe722b03f, 0xb250, 0x42ce, { 0x8e, 0xbd, 0x5b, 0xd5, 0x18, 0x12, 0xd0, 0x37 } };


// These module FILE_GUID values are read from the pinned DIZI binary INFs.
// LoadedImage with a matching FV-file path only means an image was loaded,
// NOT that driver initialization and hardware attachment succeeded.
#define DIZI_FV_XHCI_PCI     (1U << 0)
#define DIZI_FV_XHCI         (1U << 1)
#define DIZI_FV_USB_INIT     (1U << 2)
#define DIZI_FV_USB_CONFIG   (1U << 3)
#define DIZI_FV_BUTTONS      (1U << 4)
#define DIZI_FV_GPIO         (1U << 5)
#define DIZI_FV_PMIC_GLINK   (1U << 6)
#define DIZI_FV_USB_PWR      (1U << 7)

STATIC CONST EFI_GUID mDiziFvDrivers[] = {
  { 0xbeb12bee, 0xf6e1, 0x11e1, {0x9f,0xb8,0x6c,0x62,0x6d,0xe4,0xae,0xb1} }, // XhciPciEmulationDxe
  { 0xb7f50e91, 0xa759, 0x412c, {0xad,0xe4,0xdc,0xd0,0x3e,0x7f,0x7c,0x28} }, // XhciDxe
  { 0x0a134f0e, 0x075e, 0x40b3, {0x9c,0x63,0x3b,0x39,0x06,0x80,0x46,0x63} }, // UsbInitDxe
  { 0xcd823a4d, 0x7dec, 0x4531, {0xae,0x5d,0x41,0x34,0xfa,0x41,0x27,0xb8} }, // UsbConfigDxe
  { 0x5bd181db, 0x0487, 0x4f1a, {0xae,0x73,0x82,0x0e,0x16,0x56,0x11,0xb3} }, // ButtonsDxe
  { 0x569ea0de, 0xb557, 0x4043, {0x84,0xcf,0x01,0x10,0x3f,0xe5,0x16,0xe5} }, // GpiDxe
  { 0x6d4a9cf7, 0xcc0c, 0x42b0, {0xaa,0x89,0xf6,0xa6,0xa8,0xd9,0x92,0x73} }, // PmicGlinkDxe
  { 0x11faed4c, 0xb21f, 0x4d88, {0x8e,0x48,0xc4,0xc2,0x8a,0x1e,0x50,0xdf} }  // UsbPwrCtrlDxe
};


// Actual Qualcomm binary DXE_DEPEX from the pinned binary submodule
// (decoded in Actions #39731910120). INF [Depex] TRUE is misleading.
// Each bit corresponds to a PUSH GUID in the original binary, not a
// guessed MMIO register or device-tree property.
STATIC CONST EFI_GUID mButtonsDepex[] = {
  {0x387477c1, 0x69c7, 0x11d2, {0x8e,0x39,0x00,0xa0,0xc9,0x69,0x72,0x3b}},
  {0x157a5c45, 0x21b2, 0x43c5, {0xba,0x7c,0x82,0x2f,0xee,0x5f,0xe5,0x99}},
  {0x4bc5c6d7, 0x4ca4, 0x8835, {0xd1,0xbc,0xd2,0x9c,0xc2,0x02,0x5d,0x4a}},
  {0x9ba45b66, 0xefa4, 0x441c, {0xa3,0xe4,0xed,0x22,0x24,0x78,0x6b,0xe2}},
  {0xad9aec18, 0x7bf0, 0x4809, {0x9e,0x96,0x30,0x12,0x30,0x9f,0x3d,0xf7}}
};
STATIC CONST EFI_GUID mXhciPciDepex[] = {
  {0x18a031ab, 0xb443, 0x4d1a, {0xa5,0xc0,0x0c,0x09,0x26,0x1e,0x9f,0x71}},
  {0x665e3ff6, 0x46cc, 0x11d4, {0x9a,0x38,0x00,0x90,0x27,0x3f,0xc1,0x4d}},
  {0x26baccb1, 0x6f42, 0x11d4, {0xbc,0xe7,0x00,0x80,0xc7,0x3c,0x88,0x81}},
  {0x26baccb2, 0x6f42, 0x11d4, {0xbc,0xe7,0x00,0x80,0xc7,0x3c,0x88,0x81}},
  {0x1da97072, 0xbddc, 0x4b30, {0x99,0xf1,0x72,0xa0,0xb5,0x6f,0xff,0x2a}},
  {0x27cfac87, 0x46cc, 0x11d4, {0x9a,0x38,0x00,0x90,0x27,0x3f,0xc1,0x4d}},
  {0x27cfac88, 0x46cc, 0x11d4, {0x9a,0x38,0x00,0x90,0x27,0x3f,0xc1,0x4d}},
  {0xb7dfb4e1, 0x052f, 0x449f, {0x87,0xbe,0x98,0x18,0xfc,0x91,0xb7,0x33}},
  {0xa46423e3, 0x4617, 0x49f1, {0xb9,0xff,0xd1,0xbf,0xa9,0x11,0x58,0x39}},
  {0x26baccb3, 0x6f42, 0x11d4, {0xbc,0xe7,0x00,0x80,0xc7,0x3c,0x88,0x81}},
  {0x6441f818, 0x6362, 0x4e44, {0xb5,0x70,0x7d,0xba,0x31,0xdd,0x24,0x53}},
  {0x1e5668e2, 0x8481, 0x11d4, {0xbc,0xf1,0x00,0x80,0xc7,0x3c,0x88,0x81}},
  {0x665e3ff5, 0x46cc, 0x11d4, {0x9a,0x38,0x00,0x90,0x27,0x3f,0xc1,0x4d}}
};

// Read-only common ABI prefix of Qualcomm EFIUsbConfig.h revisions 1.3
// and 1.5 (BOOT.XF.3.3). Both expose 16 function pointers followed by
// UINT32 coreNum/modeType; 1.5 adds AlwaysConnected and later callbacks.
// On 64-bit UEFI, the pointer array starts at offset 8. No hardware calls.
typedef struct {
  UINT32 Revision;
  UINTN FunctionPointers[16];
  UINT32 CoreNum;
  UINT32 ModeType;
} DIZI_USB_CONFIG_ABI_PREFIX;
#define DIZI_USB_CONFIG_ABI_REVISION_103 0x00010003U
#define DIZI_USB_CONFIG_ABI_REVISION_105 0x00010005U
#define DIZI_USB_CONFIG_KNOWN_REVISION(R) ( \
  (R) == DIZI_USB_CONFIG_ABI_REVISION_103 || \
  (R) == DIZI_USB_CONFIG_ABI_REVISION_105 )
#define DIZI_USB_CORE_MAX 4U
#define DIZI_USB_MODE_HOST_XHCI 1U

typedef struct {
  EFI_SIMPLE_TEXT_INPUT_EX_PROTOCOL *Native;
  EFI_HANDLE NativeHandle;
  BOOLEAN NativeAvailable;
  DIZI_PMIC_KEYS PmicKeys;
  DIZI_SPMI_ARB_PROBE Arbiter;
  UINTN UsbHostCount;
  UINTN UsbConfigCount;
  UINT32 UsbConfigRevision[2];
  UINT32 UsbConfigCore[2];
  UINT32 UsbConfigMode[2];
  UINTN UsbConfigByDriver[2];
  UINTN UsbConfigPciEmuOwner[2];
  UINTN UsbConfigExclusive[2];
  EFI_STATUS UsbConfigSupported[2];
  BOOLEAN UsbConfigLayoutKnown[2];
  UINTN UsbOperationalCount;
  UINTN UsbDeviceCount;
  UINTN PciIoCount;
  UINTN PciRootCount;
  UINTN PmicPonCount;
  UINTN PmicGpioCount;
  UINTN PmicPwrOnCount;
  UINTN LoadedImages;
  UINTN FvFileImages;
  UINT32 DiziFvLoadedMask;
  UINT32 DiziDriverBindingMask;
  UINTN DriverBindingHandles;
  UINT32 ButtonsDepexMask;
  UINT32 XhciPciDepexMask;
  UINTN LegacyKeyCount;
  UINTN ExtendedKeyCount;
  UINT16 LastScan;
  CHAR16 LastChar;
  BOOLEAN LastWasNative;
  BOOLEAN HasLastKey;
} INPUT_STATE;

STATIC
BOOLEAN
IsQualcommKeypad (EFI_HANDLE Handle)
{
  EFI_DEVICE_PATH_PROTOCOL *Path = NULL;
  EFI_STATUS Status;
  UINTN Nodes = 0;

  Status = gBS->HandleProtocol (Handle, &gEfiDevicePathProtocolGuid, (VOID **)&Path);
  if (EFI_ERROR (Status) || Path == NULL) return FALSE;
  while (!IsDevicePathEnd (Path) && Nodes++ < 32) {
    if (DevicePathNodeLength (Path) < sizeof (EFI_DEVICE_PATH_PROTOCOL)) break;
    if (DevicePathType (Path) == HARDWARE_DEVICE_PATH &&
        DevicePathSubType (Path) == HW_VENDOR_DP &&
        DevicePathNodeLength (Path) >= sizeof (VENDOR_DEVICE_PATH)) {
      VENDOR_DEVICE_PATH *V = (VENDOR_DEVICE_PATH *)Path;
      if (CompareGuid (&V->Guid, &mKeypadGuid)) return TRUE;
    }
    Path = NextDevicePathNode (Path);
  }
  return FALSE;
}

STATIC
VOID
FindNativeKeypad (INPUT_STATE *Input)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0, Index;
  EFI_STATUS Status;

  if (Input->NativeAvailable) return;
  Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiSimpleTextInputExProtocolGuid,
                  NULL, &Count, &Handles
                  );
  if (EFI_ERROR (Status)) return;
  for (Index = 0; Index < Count; ++Index) {
    EFI_SIMPLE_TEXT_INPUT_EX_PROTOCOL *Ex = NULL;
    if (!IsQualcommKeypad (Handles[Index])) continue;
    Status = gBS->HandleProtocol (
                    Handles[Index], &gEfiSimpleTextInputExProtocolGuid,
                    (VOID **)&Ex
                    );
    if (!EFI_ERROR (Status) && Ex != NULL) {
      Input->Native = Ex;
      Input->NativeHandle = Handles[Index];
      Input->NativeAvailable = TRUE;
      break;
    }
  }
  FreePool (Handles);
}

STATIC
EFI_STATUS
StartExternalEfi (EFI_HANDLE Parent, CONST CHAR16 *Name)
{
  EFI_HANDLE *Handles = NULL;
  EFI_STATUS Status, Last = EFI_NOT_FOUND;
  UINTN Count = 0, Index;

  Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiSimpleFileSystemProtocolGuid,
                  NULL, &Count, &Handles
                  );
  if (EFI_ERROR (Status)) return Status;
  for (Index = 0; Index < Count; ++Index) {
    EFI_DEVICE_PATH_PROTOCOL *Path = FileDevicePath (Handles[Index], (CHAR16 *)Name);
    EFI_HANDLE Child = NULL;
    if (Path == NULL) { Last = EFI_OUT_OF_RESOURCES; break; }
    Status = gBS->LoadImage (FALSE, Parent, Path, NULL, 0, &Child);
    FreePool (Path);
    if (EFI_ERROR (Status)) {
      if (Status != EFI_NOT_FOUND && Status != EFI_UNSUPPORTED) Last = Status;
      continue;
    }
    Status = gBS->StartImage (Child, NULL, NULL);
    (VOID)gBS->UnloadImage (Child);
    FreePool (Handles);
    return Status;
  }
  FreePool (Handles);
  return Last;
}

// Launch the UniXNU application embedded in firmware when no FAT FS exists.
STATIC
EFI_STATUS
StartEmbeddedUniXnu (EFI_HANDLE Parent)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0, Index;
  EFI_STATUS Status, Last = EFI_NOT_FOUND;

  Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiFirmwareVolume2ProtocolGuid,
                  NULL, &Count, &Handles
                  );
  if (EFI_ERROR (Status)) return Status;
  for (Index = 0; Index < Count; ++Index) {
    EFI_FIRMWARE_VOLUME2_PROTOCOL *Fv = NULL;
    VOID *ImageData = NULL;
    UINTN ImageBytes = 0;
    UINT32 AuthenticationStatus = 0;
    EFI_HANDLE Child = NULL;

    Status = gBS->HandleProtocol (
                    Handles[Index], &gEfiFirmwareVolume2ProtocolGuid,
                    (VOID **)&Fv
                    );
    if (EFI_ERROR (Status) || Fv == NULL) {
      Last = Status;
      continue;
    }
    Status = Fv->ReadSection (
                   Fv, &mUniXnuFileGuid, EFI_SECTION_PE32, 0,
                   &ImageData, &ImageBytes, &AuthenticationStatus
                   );
    if (EFI_ERROR (Status)) {
      if (Status != EFI_NOT_FOUND) Last = Status;
      continue;
    }
    if (ImageData == NULL || ImageBytes == 0) {
      if (ImageData != NULL) FreePool (ImageData);
      Last = EFI_COMPROMISED_DATA;
      continue;
    }

    // Match the known-working DIZI BDS embedded selector loading method.
    // No filesystem or NVRAM BootOrder is required for UniXNU.efi itself.
    Status = gBS->LoadImage (
                    FALSE, Parent, NULL, ImageData, ImageBytes, &Child
                    );
    FreePool (ImageData);
    if (EFI_ERROR (Status)) {
      Last = Status;
      continue;
    }
    Status = gBS->StartImage (Child, NULL, NULL);
    (VOID)gBS->UnloadImage (Child);
    FreePool (Handles);
    return Status;
  }
  FreePool (Handles);
  return Last;
}

STATIC
UINTN
CountUsbHostControllers (VOID)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0;
  EFI_STATUS Status = gBS->LocateHandleBuffer (
                              ByProtocol, &gEfiUsb2HcProtocolGuid,
                              NULL, &Count, &Handles
                              );
  if (EFI_ERROR (Status)) return 0;
  FreePool (Handles);
  return Count;
}

STATIC
UINTN
CountOperationalUsbHostControllers (VOID)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0, Index, Operational = 0;
  EFI_STATUS Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiUsb2HcProtocolGuid, NULL, &Count, &Handles);
  if (EFI_ERROR (Status)) return 0;
  for (Index = 0; Index < Count; ++Index) {
    EFI_USB2_HC_PROTOCOL *Host = NULL;
    EFI_USB_HC_STATE State;
    Status = gBS->HandleProtocol (
                    Handles[Index], &gEfiUsb2HcProtocolGuid, (VOID **)&Host);
    if (EFI_ERROR (Status) || Host == NULL) continue;
    Status = Host->GetState (Host, &State);
    if (!EFI_ERROR (Status) && State == EfiUsbHcStateOperational) ++Operational;
  }
  FreePool (Handles);
  return Operational;
}

STATIC
UINTN
CountInputHandles (EFI_GUID *ProtocolGuid)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0;
  EFI_STATUS Status = gBS->LocateHandleBuffer (
                              ByProtocol, ProtocolGuid,
                              NULL, &Count, &Handles
                              );
  if (EFI_ERROR (Status)) return 0;
  FreePool (Handles);
  return Count;
}

STATIC
VOID
ProbeLoadedDxeModules (INPUT_STATE *Input)
{
  EFI_HANDLE *Handles = NULL;
  EFI_HANDLE *BindingHandles = NULL;
  UINTN Count = 0, BindingCount = 0, Index, DriverIndex, BindingIndex;
  EFI_STATUS Status;

  Input->LoadedImages = 0;
  Input->FvFileImages = 0;
  Input->DiziFvLoadedMask = 0;
  Input->DiziDriverBindingMask = 0;
  Input->DriverBindingHandles = 0;
  Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiDriverBindingProtocolGuid,
                  NULL, &BindingCount, &BindingHandles);
  if (!EFI_ERROR (Status))
    Input->DriverBindingHandles = BindingCount;
  else
    BindingCount = 0;
  Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiLoadedImageProtocolGuid,
                  NULL, &Count, &Handles);
  if (EFI_ERROR (Status)) {
    if (BindingHandles != NULL) FreePool (BindingHandles);
    return;
  }
  Input->LoadedImages = Count;
  for (Index = 0; Index < Count; ++Index) {
    EFI_LOADED_IMAGE_PROTOCOL *Image = NULL;
    EFI_DEVICE_PATH_PROTOCOL *Node;
    UINTN Depth = 0;

    Status = gBS->HandleProtocol (
                    Handles[Index], &gEfiLoadedImageProtocolGuid,
                    (VOID **)&Image);
    if (EFI_ERROR (Status) || Image == NULL || Image->FilePath == NULL) continue;
    Node = Image->FilePath;
    while (!IsDevicePathEnd (Node) && Depth++ < 32) {
      UINTN NodeLength = DevicePathNodeLength (Node);
      EFI_GUID FileGuid;
      if (NodeLength < sizeof (EFI_DEVICE_PATH_PROTOCOL)) break;
      if (DevicePathType (Node) == MEDIA_DEVICE_PATH &&
          DevicePathSubType (Node) == MEDIA_PIWG_FW_FILE_DP &&
          NodeLength >= sizeof (EFI_DEVICE_PATH_PROTOCOL) + sizeof (EFI_GUID)) {
        // Use CopyMem to avoid unaligned GUID loads on ARM64.
        CopyMem (&FileGuid, (UINT8 *)Node + sizeof (EFI_DEVICE_PATH_PROTOCOL),
                 sizeof (EFI_GUID));
        ++Input->FvFileImages;
        for (DriverIndex = 0;
             DriverIndex < sizeof (mDiziFvDrivers) / sizeof (mDiziFvDrivers[0]);
             ++DriverIndex) {
          if (CompareGuid (&FileGuid, &mDiziFvDrivers[DriverIndex])) {
            Input->DiziFvLoadedMask |= (1U << DriverIndex);
            // EFI_DRIVER_BINDING.ImageHandle identifies the owning image.
            // Some DXE modules are not UEFI-driver-model drivers, so an
            // absent binding is NOT proof their entry point never ran.
            for (BindingIndex = 0; BindingIndex < BindingCount; ++BindingIndex) {
              EFI_DRIVER_BINDING_PROTOCOL *Binding = NULL;
              EFI_STATUS BindingStatus = gBS->HandleProtocol (
                  BindingHandles[BindingIndex],
                  &gEfiDriverBindingProtocolGuid,
                  (VOID **)&Binding);
              if (!EFI_ERROR (BindingStatus) && Binding != NULL &&
                  Binding->ImageHandle == Handles[Index]) {
                Input->DiziDriverBindingMask |= (1U << DriverIndex);
                break;
              }
            }
          }
        }
      }
      Node = NextDevicePathNode (Node);
    }
  }
  FreePool (Handles);
  if (BindingHandles != NULL) FreePool (BindingHandles);
}


// Match the vendor driver binding to its firmware-file GUID instead of
// selecting an unrelated DriverBinding handle with the same interface type.
STATIC
EFI_DRIVER_BINDING_PROTOCOL *
FindXhciPciDriverBinding (VOID)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0, Index, Depth;
  EFI_DRIVER_BINDING_PROTOCOL *Result = NULL;
  EFI_STATUS Status;

  Status = gBS->LocateHandleBuffer (ByProtocol,
      &gEfiDriverBindingProtocolGuid, NULL, &Count, &Handles);
  if (EFI_ERROR (Status) || Handles == NULL) return NULL;

  for (Index = 0; Index < Count; ++Index) {
    EFI_DRIVER_BINDING_PROTOCOL *Binding = NULL;
    EFI_LOADED_IMAGE_PROTOCOL *Image = NULL;
    EFI_DEVICE_PATH_PROTOCOL *Node;
    Status = gBS->HandleProtocol (Handles[Index],
        &gEfiDriverBindingProtocolGuid, (VOID **)&Binding);
    if (EFI_ERROR (Status) || Binding == NULL ||
        Binding->ImageHandle == NULL || Binding->Supported == NULL)
      continue;
    Status = gBS->HandleProtocol (Binding->ImageHandle,
        &gEfiLoadedImageProtocolGuid, (VOID **)&Image);
    if (EFI_ERROR (Status) || Image == NULL || Image->FilePath == NULL)
      continue;
    Node = Image->FilePath;
    for (Depth = 0; !IsDevicePathEnd (Node) && Depth < 32; ++Depth) {
      EFI_GUID FileGuid;
      UINTN Length = DevicePathNodeLength (Node);
      if (Length < sizeof (EFI_DEVICE_PATH_PROTOCOL)) break;
      if (DevicePathType (Node) == MEDIA_DEVICE_PATH &&
          DevicePathSubType (Node) == MEDIA_PIWG_FW_FILE_DP &&
          Length >= sizeof (EFI_DEVICE_PATH_PROTOCOL) + sizeof (EFI_GUID)) {
        CopyMem (&FileGuid, (UINT8 *)Node + sizeof (EFI_DEVICE_PATH_PROTOCOL),
                 sizeof (EFI_GUID));
        if (CompareGuid (&FileGuid, &mDiziFvDrivers[0])) {
          Result = Binding;
          break;
        }
      }
      Node = NextDevicePathNode (Node);
    }
    if (Result != NULL) break;
  }
  FreePool (Handles);
  return Result;
}

// Vendor XhciPciEmulationDriverBindingSupported checks coreNum < 4 and
// modeType == USB_HOST_MODE_XHCI. Capture this actual decision for BOTH
// config handles. Supported() opens/closes protocol; it does not call the
// hardware-changing ConfigUsb(), in the inspected Qualcomm implementation.
STATIC
VOID
ProbeUsbConfigSupported (INPUT_STATE *Input)
{
  EFI_HANDLE *Handles = NULL;
  EFI_DRIVER_BINDING_PROTOCOL *Binding;
  UINTN Count = 0, Index;
  EFI_STATUS Status;

  Binding = FindXhciPciDriverBinding ();
  Status = gBS->LocateHandleBuffer (ByProtocol,
      &mDiziUsbConfigProtocolGuid, NULL, &Count, &Handles);
  if (EFI_ERROR (Status) || Handles == NULL) return;
  for (Index = 0; Index < Count && Index < 2; ++Index) {
    DIZI_USB_CONFIG_ABI_PREFIX *Config = NULL;
    EFI_OPEN_PROTOCOL_INFORMATION_ENTRY *Info = NULL;
    UINTN InfoCount = 0, I;
    Input->UsbConfigSupported[Index] = EFI_NOT_FOUND;
    Input->UsbConfigRevision[Index] = 0;
    Input->UsbConfigLayoutKnown[Index] = FALSE;
    Input->UsbConfigByDriver[Index] = 0;
    Input->UsbConfigPciEmuOwner[Index] = 0;
    Input->UsbConfigExclusive[Index] = 0;
    // OpenProtocolInformation is observation only. It can distinguish
    // another driver controlling the port from an unsupported host mode.
    Status = gBS->OpenProtocolInformation (Handles[Index],
        &mDiziUsbConfigProtocolGuid, &Info, &InfoCount);
    if (!EFI_ERROR (Status) && Info != NULL) {
      for (I = 0; I < InfoCount; ++I) {
        if ((Info[I].Attributes & EFI_OPEN_PROTOCOL_BY_DRIVER) != 0) {
          ++Input->UsbConfigByDriver[Index];
          // A PCEMU owner on a handle WITHOUT PCI IO can indicate that
          // its vendor Start() opened the protocol and failed later.
          // Observe ownership only; never steal or close the handle.
          if (Binding != NULL &&
              Info[I].AgentHandle == Binding->DriverBindingHandle)
            ++Input->UsbConfigPciEmuOwner[Index];
        }
        if ((Info[I].Attributes & EFI_OPEN_PROTOCOL_EXCLUSIVE) != 0)
          ++Input->UsbConfigExclusive[Index];
      }
      FreePool (Info);
    }
    Status = gBS->HandleProtocol (Handles[Index],
        &mDiziUsbConfigProtocolGuid, (VOID **)&Config);
    if (EFI_ERROR (Status) || Config == NULL) {
      Input->UsbConfigSupported[Index] = Status;
      continue;
    }
    Input->UsbConfigRevision[Index] = Config->Revision;
    if (DIZI_USB_CONFIG_KNOWN_REVISION (Config->Revision)) {
      Input->UsbConfigCore[Index] = Config->CoreNum;
      Input->UsbConfigMode[Index] = Config->ModeType;
      Input->UsbConfigLayoutKnown[Index] = TRUE;
    }
    if (Binding != NULL)
      Input->UsbConfigSupported[Index] =
        Binding->Supported (Binding, Handles[Index], NULL);
  }
  FreePool (Handles);
}

STATIC
UINT32
ProbeDependencyProtocols (CONST EFI_GUID *Guids, UINTN Count)
{
  UINT32 Mask = 0;
  UINTN Index;
  if (Count > 31) return 0;
  for (Index = 0; Index < Count; ++Index) {
    EFI_GUID Id;
    EFI_HANDLE *Handles = NULL;
    UINTN HandleCount = 0;
    EFI_STATUS Status;
    // DXE DEPEX evaluates whether a GUID was INSTALLED. Architectural
    // marker protocols deliberately register with Interface == NULL
    // (Reset/RTC/Monotonic/Variable). Checking a non-null interface
    // falsely reports every such prerequisite as missing.
    // LocateHandleBuffer is read-only and counts even NULL interfaces.
    CopyMem (&Id, &Guids[Index], sizeof (Id));
    Status = gBS->LocateHandleBuffer (
                    ByProtocol, &Id, NULL, &HandleCount, &Handles);
    if (!EFI_ERROR (Status) && HandleCount != 0)
      Mask |= (1U << Index);
    if (Handles != NULL) FreePool (Handles);
  }
  return Mask;
}

STATIC
UINTN
CountBits (UINT32 Mask)
{
  UINTN Count = 0;
  while (Mask != 0) {
    Mask &= (Mask - 1U);
    ++Count;
  }
  return Count;
}

STATIC
VOID
Render (UINTN Selected, CONST INPUT_STATE *Input)
{
  // A fixed, readable screen: no diagnostics carousel or hidden pages.
  // Keep all lines <= 46 ASCII characters for both GOP and ConOut fallback.
  CHAR8 MenuAndroid[48], MenuXnu[48], MenuExit[48];
  CHAR8 MenuHeader[48];
  CHAR8 KeyStatus[48], PmicStatus[48];
  CHAR8 LastKeyStatus[48];
  CHAR8 PmicKeyStatus0[48], PmicKeyStatus1[48];
  CHAR8 ArbStatus[48], MapStatus[48];
  CONST CHAR8 *Lines[15];
  UINTN Index;
  UINTN ButtonDepex = CountBits (Input->ButtonsDepexMask);

  AsciiSPrint (MenuAndroid, sizeof(MenuAndroid), "%a ANDROID     [LOADER MISSING]",
              Selected == 0 ? ">" : " ");
  AsciiSPrint (MenuXnu, sizeof(MenuXnu), "%a XNU/DARWIN  [LOADER MISSING]",
              Selected == 1 ? ">" : " ");
  AsciiSPrint (MenuExit, sizeof(MenuExit), "%a RETURN TO FIRMWARE",
              Selected == 2 ? ">" : " ");
  AsciiSPrint (KeyStatus, sizeof(KeyStatus),
              "BUTTONS:%a  DEP:%u/5",
              Input->NativeAvailable ? "NATIVE" :
                  ((Input->PmicKeys.PonValid && Input->PmicKeys.GpioValid) ?
                    (Input->PmicKeys.ArbiterAvailable ? "ARB" : "SPMI") :
                    "MISSING"),
              (UINT32)ButtonDepex);
  // The board DT places Volume Up on PM6450 SID1 GPIO1 and
  // Power/Volume Down on PMK8350 SID0 PON/RESIN. Merely having
  // PmicGlinkDxe loaded is not a native key input provider.
  AsciiSPrint (PmicStatus, sizeof(PmicStatus),
              "INPUT SPMI:%u ARB:%u GPIO:%u PWR:%u",
              Input->PmicKeys.SpmiAvailable ? 1U : 0U,
              Input->PmicKeys.ArbiterAvailable ? 1U : 0U,
              (UINT32)Input->PmicGpioCount,
              (UINT32)Input->PmicPwrOnCount);
  AsciiSPrint (ArbStatus, sizeof(ArbStatus),
              "ARB:%08X F0:%08X F1:%08X",
              Input->Arbiter.Version,
              Input->Arbiter.Features,
              Input->Arbiter.FeaturesBus1);
  AsciiSPrint (MapStatus, sizeof(MapStatus),
              "APIDS:%u PON:%a %u VOL+:%a %u",
              Input->Arbiter.ApidCount,
              Input->Arbiter.PonMapped ? "YES" : "NO",
              Input->Arbiter.PonApid,
              Input->Arbiter.GpioMapped ? "YES" : "NO",
              Input->Arbiter.GpioApid);
  if (Input->HasLastKey)
    AsciiSPrint (LastKeyStatus, sizeof(LastKeyStatus),
                "LAST KEY: %a SCAN=%04X CHAR=%04X",
                Input->LastWasNative ? "NATIVE" : "CONSOLE",
                (UINT32)Input->LastScan, (UINT32)Input->LastChar);
  else
    AsciiSPrint (LastKeyStatus, sizeof(LastKeyStatus), "LAST KEY: NONE");

  AsciiSPrint (MenuHeader, sizeof(MenuHeader),
              "DIZI / SM7435  %a", DIZI_BUILD_STAMP);
  Lines[0] = MenuHeader;
  Lines[1] = "----------------------------------------";
  Lines[2] = MenuAndroid;
  Lines[3] = MenuXnu;
  Lines[4] = MenuExit;
  Lines[5] = "----------------------------------------";
  Lines[6] = KeyStatus;
  Lines[7] = PmicStatus;
  Lines[8] = ArbStatus;
  Lines[9] = MapStatus;
  if (Input->Arbiter.MapSamplesValid && !Input->PmicKeys.SpmiAvailable) {
    // Raw map entries are diagnostic snapshots, NOT verified APID mappings.
    AsciiSPrint (PmicKeyStatus0, sizeof(PmicKeyStatus0),
                "RAW MAP[0]:%08X [1]:%08X",
                Input->Arbiter.MapSample0, Input->Arbiter.MapSample1);
    AsciiSPrint (PmicKeyStatus1, sizeof(PmicKeyStatus1),
                "RAW MAP[16]:%08X [128]:%08X",
                Input->Arbiter.MapSample16, Input->Arbiter.MapSample128);
  } else {
    AsciiSPrint (PmicKeyStatus0, sizeof(PmicKeyStatus0),
                "PON:%a R:%02X E:%02X P:%u D:%u",
                Input->PmicKeys.PonValid ? "OK" : "NO",
                Input->PmicKeys.PonRaw,
                Input->PmicKeys.PonResult,
                Input->PmicKeys.PowerDown ? 1U : 0U,
                Input->PmicKeys.VolDown ? 1U : 0U);
    AsciiSPrint (PmicKeyStatus1, sizeof(PmicKeyStatus1),
                "GPIO:%a R:%02X E:%02X U:%u F:%u",
                Input->PmicKeys.GpioValid ? "OK" : "NO",
                Input->PmicKeys.GpioRaw,
                Input->PmicKeys.GpioResult,
                Input->PmicKeys.VolUp ? 1U : 0U,
                Input->PmicKeys.ReadFailures);
  }

  Lines[10] = PmicKeyStatus0;
  Lines[11] = PmicKeyStatus1;
  Lines[12] = LastKeyStatus;
  Lines[13] = "VOL: MOVE   POWER/ENTER: SELECT";
  Lines[14] = "60S IDLE RETURN  /  NO STORAGE WRITES";

  if (DiziDrawScaledUi (Lines, 15)) return;

  // GOP unavailable or Blt failed: retain reliable stock text console.
  gST->ConOut->ClearScreen (gST->ConOut);
  for (Index = 0; Index < 15; ++Index)
    Print (L"%a\r\n", Lines[Index]);
}

STATIC
BOOLEAN
PollKey (INPUT_STATE *Input, EFI_INPUT_KEY *Key, BOOLEAN *FromNative)
{
  EFI_STATUS Status;
  EFI_KEY_DATA Data;

  // Poll the dedicated vendor keypad first, not only the ConSplitter.
  // On this firmware the keypad does not necessarily surface as ConIn.
  if (Input->Native != NULL) {
    Status = Input->Native->ReadKeyStrokeEx (Input->Native, &Data);
    if (!EFI_ERROR (Status)) {
      *Key = Data.Key;
      *FromNative = TRUE;
      return TRUE;
    }
  }

  // ConIn may contain ONLY the Qualcomm keypad. Keep it as a fallback.
  if (gST->ConIn != NULL) {
    Status = gST->ConIn->ReadKeyStroke (gST->ConIn, Key);
    if (!EFI_ERROR (Status)) {
      *FromNative = FALSE;
      return TRUE;
    }
  }

  // USB keyboards started after BDS console configuration may never be
  // attached to ConSplitter/ConIn. Scan all independently installed EX
  // input protocols and read them directly as a second fallback.
  {
    EFI_HANDLE *Handles = NULL;
    UINTN Count = 0, Index;
    Status = gBS->LocateHandleBuffer (
                    ByProtocol, &gEfiSimpleTextInputExProtocolGuid,
                    NULL, &Count, &Handles
                    );
    if (!EFI_ERROR (Status)) {
      for (Index = 0; Index < Count; ++Index) {
        EFI_SIMPLE_TEXT_INPUT_EX_PROTOCOL *Ex = NULL;
        EFI_KEY_DATA Data;
        if (Handles[Index] == Input->NativeHandle ||
            Handles[Index] == gST->ConsoleInHandle) continue;
        if (EFI_ERROR (gBS->HandleProtocol (
                            Handles[Index],
                            &gEfiSimpleTextInputExProtocolGuid,
                            (VOID **)&Ex
                            )) || Ex == NULL) continue;
        Status = Ex->ReadKeyStrokeEx (Ex, &Data);
        if (!EFI_ERROR (Status)) {
          *Key = Data.Key;
          *FromNative = IsQualcommKeypad (Handles[Index]);
          FreePool (Handles);
          return TRUE;
        }
      }
      FreePool (Handles);
    }
  }
  // Some Qualcomm ButtonsDxe builds install only EFI_SIMPLE_TEXT_INPUT
  // on a vendor handle, rather than SimpleTextInputEx or a ConSplitter path.
  // The old selector did not poll these handles at all.
  {
    EFI_HANDLE *Handles = NULL;
    UINTN Count = 0, Index;
    Status = gBS->LocateHandleBuffer (
                    ByProtocol, &gEfiSimpleTextInProtocolGuid,
                    NULL, &Count, &Handles);
    if (!EFI_ERROR (Status)) {
      for (Index = 0; Index < Count; ++Index) {
        EFI_SIMPLE_TEXT_INPUT_PROTOCOL *Basic = NULL;
        if (Handles[Index] == gST->ConsoleInHandle ||
            Handles[Index] == Input->NativeHandle) continue;
        Status = gBS->HandleProtocol (
                        Handles[Index], &gEfiSimpleTextInProtocolGuid,
                        (VOID **)&Basic);
        if (EFI_ERROR (Status) || Basic == NULL) continue;
        Status = Basic->ReadKeyStroke (Basic, Key);
        if (!EFI_ERROR (Status)) {
          *FromNative = IsQualcommKeypad (Handles[Index]);
          FreePool (Handles);
          return TRUE;
        }
      }
      FreePool (Handles);
    }
  }
  return FALSE;
}

STATIC
INTN
DecodeKey (CONST EFI_INPUT_KEY *Key)
{
  if (Key->ScanCode == SCAN_UP || Key->ScanCode == SCAN_VOLUME_UP) return 0;
  if (Key->ScanCode == SCAN_DOWN || Key->ScanCode == SCAN_VOLUME_DOWN) return 1;
  if (Key->ScanCode == SCAN_SUSPEND ||
      Key->UnicodeChar == CHAR_CARRIAGE_RETURN) return 2;
  if (Key->ScanCode == SCAN_ESC ||
      Key->UnicodeChar == L'q' || Key->UnicodeChar == L'Q') return 3;
  if (Key->UnicodeChar == L'a' || Key->UnicodeChar == L'A') return 4;
  if (Key->UnicodeChar == L'x' || Key->UnicodeChar == L'X') return 5;
  // Unknown Power key codes remain visible for diagnostic purposes.
  return -1;
}

EFI_STATUS
EFIAPI
UefiMain (EFI_HANDLE ImageHandle, EFI_SYSTEM_TABLE *SystemTable)
{
  INPUT_STATE Input = {0};
  EFI_EVENT Tick = NULL;
  EFI_STATUS Status;
  EFI_INPUT_KEY Key, PmicKey, PriorKey = {0};
  BOOLEAN Native, PmicPressed, PriorNative = FALSE, HavePrior = FALSE;
  UINTN Selected = 0, IdleTicks = 0, TickIndex, PriorTick = 0, NowTick = 0;
  INTN Action;
  (VOID)SystemTable;

  if (gST->ConOut == NULL) return EFI_UNSUPPORTED;
  FindNativeKeypad (&Input);
  DiziProbeSpmiArbiterReadOnly (&Input.Arbiter);
  Input.UsbHostCount = CountUsbHostControllers ();
  Input.UsbConfigCount = CountInputHandles (&mDiziUsbConfigProtocolGuid);
  Input.UsbOperationalCount = CountOperationalUsbHostControllers ();
  Input.UsbDeviceCount = CountInputHandles (&gEfiUsbIoProtocolGuid);
  Input.PciIoCount = CountInputHandles (&gEfiPciIoProtocolGuid);
  Input.PciRootCount = CountInputHandles (&gEfiPciRootBridgeIoProtocolGuid);
  Input.PmicPonCount = CountInputHandles (&mPmicPonProtocolGuid);
  Input.PmicGpioCount = CountInputHandles (&mPmicGpioProtocolGuid);
  Input.PmicPwrOnCount = CountInputHandles (&mPmicPwrOnProtocolGuid);
  Input.LegacyKeyCount = CountInputHandles (&gEfiSimpleTextInProtocolGuid);
  Input.ExtendedKeyCount = CountInputHandles (&gEfiSimpleTextInputExProtocolGuid);
  ProbeLoadedDxeModules (&Input);
  ProbeUsbConfigSupported (&Input);
  Input.ButtonsDepexMask = ProbeDependencyProtocols (
                             mButtonsDepex,
                             sizeof (mButtonsDepex) / sizeof (mButtonsDepex[0]));
  Input.XhciPciDepexMask = ProbeDependencyProtocols (
                             mXhciPciDepex,
                             sizeof (mXhciPciDepex) / sizeof (mXhciPciDepex[0]));
  Status = gBS->CreateEvent (EVT_TIMER, TPL_CALLBACK, NULL, NULL, &Tick);
  if (EFI_ERROR (Status)) return Status;
  Status = gBS->SetTimer (Tick, TimerPeriodic, TICK_100NS);
  if (EFI_ERROR (Status)) { gBS->CloseEvent (Tick); return Status; }

  Render (Selected, &Input);
  while (IdleTicks < TIMEOUT_TICKS) {
    // Polling works even when a Qualcomm keypad lacks WaitForKeyEx signalling.
    Status = gBS->WaitForEvent (1, &Tick, &TickIndex);
    if (EFI_ERROR (Status)) break;
    ++NowTick;
    ++IdleTicks;
    // Some Qualcomm devices install input protocols late in DXE.
    if ((NowTick % 20) == 0) {
      BOOLEAN WasNative = Input.NativeAvailable;
      UINTN PriorUsbHostCount = Input.UsbHostCount;
      UINTN PriorUsbConfigCount = Input.UsbConfigCount;
      UINTN PriorOperationalCount = Input.UsbOperationalCount;
      UINTN PriorDeviceCount = Input.UsbDeviceCount;
      UINTN PriorPciIoCount = Input.PciIoCount;
      UINTN PriorPciRootCount = Input.PciRootCount;
      UINTN PriorPmicPonCount = Input.PmicPonCount;
      UINTN PriorPmicGpioCount = Input.PmicGpioCount;
      UINTN PriorPmicPwrOnCount = Input.PmicPwrOnCount;
      UINTN PriorBasicCount = Input.LegacyKeyCount;
      UINTN PriorExtendedCount = Input.ExtendedKeyCount;
      UINTN PriorImageCount = Input.LoadedImages;
      UINTN PriorFvCount = Input.FvFileImages;
      UINT32 PriorDxeMask = Input.DiziFvLoadedMask;
      UINT32 PriorBindingMask = Input.DiziDriverBindingMask;
      UINTN PriorBindingCount = Input.DriverBindingHandles;
      UINT32 PriorButtonsDepex = Input.ButtonsDepexMask;
      UINT32 PriorXhciDepex = Input.XhciPciDepexMask;
      if (!Input.NativeAvailable) FindNativeKeypad (&Input);
      Input.UsbHostCount = CountUsbHostControllers ();
      Input.UsbConfigCount = CountInputHandles (&mDiziUsbConfigProtocolGuid);
      Input.UsbOperationalCount = CountOperationalUsbHostControllers ();
      Input.UsbDeviceCount = CountInputHandles (&gEfiUsbIoProtocolGuid);
      Input.PciIoCount = CountInputHandles (&gEfiPciIoProtocolGuid);
      Input.PciRootCount = CountInputHandles (&gEfiPciRootBridgeIoProtocolGuid);
      Input.PmicPonCount = CountInputHandles (&mPmicPonProtocolGuid);
      Input.PmicGpioCount = CountInputHandles (&mPmicGpioProtocolGuid);
      Input.PmicPwrOnCount = CountInputHandles (&mPmicPwrOnProtocolGuid);
      Input.LegacyKeyCount = CountInputHandles (&gEfiSimpleTextInProtocolGuid);
      Input.ExtendedKeyCount = CountInputHandles (&gEfiSimpleTextInputExProtocolGuid);
      ProbeLoadedDxeModules (&Input);
      if (PriorUsbConfigCount != Input.UsbConfigCount)
        ProbeUsbConfigSupported (&Input);
      Input.ButtonsDepexMask = ProbeDependencyProtocols (
                                 mButtonsDepex,
                                 sizeof (mButtonsDepex) / sizeof (mButtonsDepex[0]));
      Input.XhciPciDepexMask = ProbeDependencyProtocols (
                                 mXhciPciDepex,
                                 sizeof (mXhciPciDepex) / sizeof (mXhciPciDepex[0]));
      if (WasNative != Input.NativeAvailable ||
          PriorImageCount != Input.LoadedImages ||
          PriorFvCount != Input.FvFileImages ||
          PriorDxeMask != Input.DiziFvLoadedMask ||
          PriorBindingMask != Input.DiziDriverBindingMask ||
          PriorBindingCount != Input.DriverBindingHandles ||
          PriorButtonsDepex != Input.ButtonsDepexMask ||
          PriorXhciDepex != Input.XhciPciDepexMask ||
          PriorUsbHostCount != Input.UsbHostCount ||
          PriorUsbConfigCount != Input.UsbConfigCount ||
          PriorOperationalCount != Input.UsbOperationalCount ||
          PriorDeviceCount != Input.UsbDeviceCount ||
          PriorPciIoCount != Input.PciIoCount ||
          PriorPciRootCount != Input.PciRootCount ||
          PriorPmicPonCount != Input.PmicPonCount ||
          PriorPmicGpioCount != Input.PmicGpioCount ||
          PriorPmicPwrOnCount != Input.PmicPwrOnCount ||
          PriorBasicCount != Input.LegacyKeyCount ||
          PriorExtendedCount != Input.ExtendedKeyCount)
        Render (Selected, &Input);
    }

    {
      UINT8 OldPonRaw = Input.PmicKeys.PonRaw;
      UINT8 OldGpioRaw = Input.PmicKeys.GpioRaw;
      BOOLEAN OldPonValid = Input.PmicKeys.PonValid;
      BOOLEAN OldGpioValid = Input.PmicKeys.GpioValid;
      BOOLEAN OldSpmi = Input.PmicKeys.SpmiAvailable;
      BOOLEAN OldArb = Input.PmicKeys.ArbiterAvailable;
      UINT32 OldReadFailures = Input.PmicKeys.ReadFailures;

      DiziPmicSampleKeys (&Input.PmicKeys, &Input.Arbiter,
                          (UINT32)NowTick, &PmicKey, &PmicPressed);
      if (OldPonRaw != Input.PmicKeys.PonRaw ||
          OldGpioRaw != Input.PmicKeys.GpioRaw ||
          OldPonValid != Input.PmicKeys.PonValid ||
          OldGpioValid != Input.PmicKeys.GpioValid ||
          OldSpmi != Input.PmicKeys.SpmiAvailable ||
          OldArb != Input.PmicKeys.ArbiterAvailable ||
          OldReadFailures != Input.PmicKeys.ReadFailures)
        Render (Selected, &Input);
    }

    Native = FALSE;
    if (PmicPressed) {
      // ReadLong edge from actual PMIC is a physical key press.
      Key = PmicKey;
      Native = TRUE;
    } else if (!PollKey (&Input, &Key, &Native)) continue;

    Input.LastScan = Key.ScanCode;
    Input.LastChar = Key.UnicodeChar;
    Input.LastWasNative = Native;
    Input.HasLastKey = TRUE;

    // Suppress duplicate key events from ConSplitter + native protocol.
    if (HavePrior && (NowTick - PriorTick) <= 3 &&
        PriorKey.ScanCode == Key.ScanCode &&
        PriorKey.UnicodeChar == Key.UnicodeChar) continue;
    PriorKey = Key;
    PriorNative = Native;
    (VOID)PriorNative;
    PriorTick = NowTick;
    HavePrior = TRUE;
    IdleTicks = 0;
    Action = DecodeKey (&Key);
    if (Action == 0) Selected = (Selected + 2) % 3;
    else if (Action == 1) Selected = (Selected + 1) % 3;
    else if (Action == 3) break;
    else if (Action == 4) Selected = 0;
    else if (Action == 5) Selected = 1;
    Render (Selected, &Input);

    if (Action == 2) {
      if (Selected == 2) break;
      gBS->CloseEvent (Tick);
      Status = StartExternalEfi (
                 ImageHandle, Selected == 0 ? ANDROID_LOADER : DARWIN_LOADER
                 );
      if (Selected == 1 && (Status == EFI_NOT_FOUND || Status == EFI_UNSUPPORTED)) {
        Status = StartEmbeddedUniXnu (ImageHandle);
      }
      if (EFI_ERROR (Status)) {
        Print (L"\r\nEFI OS loader failed: %r\r\n", Status);
      } else {
        Print (L"\r\nEFI loader returned normally; XNU execution is not confirmed.\r\n");
      }
      Print (L"No partition changes. Returning to BDS.\r\n");
      gBS->Stall (3000000);
      return Status;
    }
  }
  gBS->CloseEvent (Tick);
  return EFI_SUCCESS;
}

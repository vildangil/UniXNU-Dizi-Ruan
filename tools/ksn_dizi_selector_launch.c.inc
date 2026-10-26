/*
 * DeviceBootManagerAfterConsole() calls DiziLaunchEmbeddedSelector() to run
 * the UEFI_APPLICATION stored in FVMAIN from the native BDS startup path.
 *
 * Not a boot.img parser; it does not initialize an Android or XNU kernel.
 * Run from temporary firmware only until platform input and fallbacks tested.
 */

// The upstream BDS normally emits UsbControllerInitGuid only in the
// OnDemandConInConnect phase, AFTER this board's embedded boot menu starts.
// Bring host-mode probing forward so OTG HID keyboards can work in the menu.
// This does not replace Qualcomm Type-C VBUS/PHY/role-switch firmware.
// This is the Qualcomm USB Config protocol GUID from EFIUsbConfig.h,
// not gUsbControllerInitGuid (which is an event group).
// XhciPciEmulationDxe::DriverBindingSupported consumes it directly.
// Never register a substitute protocol: a fake instance cannot init PHY.
STATIC EFI_GUID mDiziUsbConfigProtocolGuid =
  { 0xe722b03f, 0xb250, 0x42ce, { 0x8e, 0xbd, 0x5b, 0xd5, 0x18, 0x12, 0xd0, 0x37 } };

STATIC BOOLEAN mDiziUsbInitTriggered = FALSE;

STATIC
VOID
EFIAPI
DiziUsbEarlyNotify (
  IN EFI_EVENT Event,
  IN VOID *Context
  )
{
  (VOID)Event;
  (VOID)Context;
}

// EDK2's ordinary ConnectController path may publish EFI_PCI_IO on
// a child only after its parent root bridge has been connected.
// Never create a fake PCI root or expose a hardcoded DWC3 MMIO BAR.
// If the genuine parent handles do not exist, this is a no-op.
STATIC
UINTN
DiziConnectExistingProtocolControllers (IN EFI_GUID *ProtocolGuid)
{
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0, Index, Connected = 0;
  EFI_STATUS Status;

  Status = gBS->LocateHandleBuffer (ByProtocol, ProtocolGuid,
                                    NULL, &Count, &Handles);
  if (EFI_ERROR (Status) || Handles == NULL)
    return 0;

  // Use the UEFI driver model, not explicit vendor Supported()/Start()
  // calls or arbitrary SPMI/USB PHY register writes.
  for (Index = 0; Index < Count; ++Index) {
    Status = gBS->ConnectController (Handles[Index], NULL, NULL, TRUE);
    if (!EFI_ERROR (Status) || Status == EFI_ALREADY_STARTED)
      ++Connected;
    DEBUG ((DEBUG_INFO, "[dizi usb] Connect existing %g[%u]: %r\n",
            ProtocolGuid, (UINT32)Index, Status));
  }
  gBS->FreePool (Handles);
  return Connected;
}

STATIC
VOID
DiziInitUsbHostEarly (VOID)
{
  EFI_STATUS Status;
  EFI_EVENT  InitEvent = NULL;
  EFI_HANDLE *Controllers = NULL;
  UINTN Count = 0, Index;
  UINTN ConnectedUsbConfig, ConnectedRootBridge, ConnectedPciIo;

  if (mDiziUsbInitTriggered) {
    return;
  }

  Status = gBS->CreateEventEx (
                  EVT_NOTIFY_SIGNAL, TPL_CALLBACK,
                  DiziUsbEarlyNotify, NULL,
                  &gUsbControllerInitGuid, &InitEvent
                  );
  if (EFI_ERROR (Status)) {
    DEBUG ((DEBUG_ERROR, "[dizi otg] Cannot create USB init event: %r\n", Status));
    return;
  }
  Status = gBS->SignalEvent (InitEvent);
  gBS->CloseEvent (InitEvent);
  if (EFI_ERROR (Status)) {
    DEBUG ((DEBUG_WARN, "[dizi otg] Cannot signal USB init: %r\n", Status));
    return;
  }
  mDiziUsbInitTriggered = TRUE;

  // Allow the precompiled Qualcomm UsbInit/UsbPwrCtrl drivers to
  // run before attaching real UEFI parent/controller handles.
  gBS->Stall (500000);

  // Core discovery is exposed through USB Config, not through PCI IO.
  // Connecting the genuine protocol handle invokes the vendor
  // XhciPciEmulationDxe Supported()/Start() via the UEFI driver model.
  // Its Start() may request USB_HOST_MODE_XHCI from vendor USB Config.
  // This is an experimental, temporary-boot-only hardware transition.
  // These calls MUST stay outside DEBUG(); RELEASE firmware drops
  // DEBUG expressions entirely, including any arguments with side effects.
  ConnectedUsbConfig = DiziConnectExistingProtocolControllers (
                         &mDiziUsbConfigProtocolGuid);
  ConnectedRootBridge = DiziConnectExistingProtocolControllers (
                          &gEfiPciRootBridgeIoProtocolGuid);
  ConnectedPciIo = DiziConnectExistingProtocolControllers (
                     &gEfiPciIoProtocolGuid);
  DEBUG ((DEBUG_INFO, "[dizi usb] config=%u root=%u pciio=%u\n",
          (UINT32)ConnectedUsbConfig, (UINT32)ConnectedRootBridge,
          (UINT32)ConnectedPciIo));
  (VOID)ConnectedUsbConfig;
  (VOID)ConnectedRootBridge;
  (VOID)ConnectedPciIo;

  Status = gBS->LocateHandleBuffer (
                  ByProtocol, &gEfiUsb2HcProtocolGuid,
                  NULL, &Count, &Controllers
                  );
  if (EFI_ERROR (Status)) {
    DEBUG ((DEBUG_WARN, "[dizi otg] No USB2 host controllers after init: %r\n", Status));
    return;
  }

  DEBUG ((DEBUG_INFO, "[dizi otg] USB2 host controller handles: %u\n", (UINT32)Count));
  for (Index = 0; Index < Count; ++Index) {
    Status = gBS->ConnectController (Controllers[Index], NULL, NULL, TRUE);
    DEBUG ((DEBUG_INFO, "[dizi otg] ConnectController[%u]: %r\n", (UINT32)Index, Status));
  }
  gBS->FreePool (Controllers);
}

STATIC EFI_GUID mDiziSelectorFfsGuid =
  { 0x8b56dab9, 0xa18d, 0x40a4, { 0x97, 0xec, 0xdf, 0xcc, 0x72, 0xee, 0x1f, 0x66 } };

STATIC
VOID
DiziLaunchEmbeddedSelector (VOID)
{
  EFI_HANDLE                    *FvHandles = NULL;
  UINTN                         Count = 0;
  UINTN                         Index;
  EFI_STATUS                    Status;

  Status = gBS->LocateHandleBuffer (
                  ByProtocol,
                  &gEfiFirmwareVolume2ProtocolGuid,
                  NULL,
                  &Count,
                  &FvHandles
                  );
  if (EFI_ERROR (Status)) {
    DEBUG ((DEBUG_WARN, "[dizi selector] No FV2 handles: %r\n", Status));
    return;
  }

  for (Index = 0; Index < Count; ++Index) {
    EFI_FIRMWARE_VOLUME2_PROTOCOL  *Fv = NULL;
    VOID                           *ImageData = NULL;
    UINTN                          ImageBytes = 0;
    UINT32                         AuthenticationStatus = 0;
    EFI_HANDLE                     LoadedImage = NULL;

    Status = gBS->HandleProtocol (
                    FvHandles[Index],
                    &gEfiFirmwareVolume2ProtocolGuid,
                    (VOID **)&Fv
                    );
    if (EFI_ERROR (Status)) {
      continue;
    }

    Status = Fv->ReadSection (
                   Fv,
                   &mDiziSelectorFfsGuid,
                   EFI_SECTION_PE32,
                   0,
                   &ImageData,
                   &ImageBytes,
                   &AuthenticationStatus
                   );
    if (EFI_ERROR (Status)) {
      continue;
    }

    if (ImageData == NULL || ImageBytes == 0) {
      if (ImageData != NULL) {
        gBS->FreePool (ImageData);
      }
      break;
    }

    /*
     * Deliberately loading from FV image bytes, not from an untrusted
     * external path. No persistent boot variables are modified.
     */
    Status = gBS->LoadImage (
                    FALSE,
                    gImageHandle,
                    NULL,
                    ImageData,
                    ImageBytes,
                    &LoadedImage
                    );
    gBS->FreePool (ImageData);
    if (EFI_ERROR (Status)) {
      DEBUG ((DEBUG_ERROR, "[dizi selector] LoadImage failed: %r\n", Status));
      break;
    }

    Status = gBS->StartImage (LoadedImage, NULL, NULL);
    DEBUG ((DEBUG_INFO, "[dizi selector] Returned from menu: %r\n", Status));
    (VOID)gBS->UnloadImage (LoadedImage);
    break;
  }

  gBS->FreePool (FvHandles);
}

# UniXNU Dizi / Ruan

Experimental [UniXNU](https://github.com/UniXNU/UniXNU) port for Xiaomi Redmi Pad Pro (`dizi`, Snapdragon SM7435). The `ruan` variant is not separately verified.

**Current stage:** EDK2 and the UniXNU graphical menu start on dizi using temporary `fastboot boot`. The payload is still not mounted: the FDT initrd buffer starts with LZ4 Legacy magic `0x184C2102`. XNU kernel entry, storage, GPU and iPadOS userland are not verified.

## Ownership

- **Device repository (this repo):** `board.toml`, defconfig, DTS, device evidence, eventual device drivers and boot profile.
- **[Mu-Silicium](https://github.com/vildangil/Mu-Silicium):** EDK2, BootShim, firmware configuration and PMIC/SPMI.
- **[UniXNU](https://github.com/UniXNU/UniXNU):** generic boot manager, DarwinBoot and shared components.

The checkout was initially derived from `UniXNU-sheng` (SM8550). Its drivers, MMIO values, firmware and iPadOS-specific settings must not be used on SM7435. Native XNU builds remain blocked pending device-specific verification.

## Building EDK2 on GitHub

Open [Actions → Dizi standalone UEFI + UniXNU (public only)](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/build.yml), choose **Run workflow**, and select **main**. No self-hosted runner or additional repository secret is required.

The workflow uses **only public** pinned [Mu-Silicium](https://github.com/vildangil/Mu-Silicium) and [upstream UniXNU](https://github.com/UniXNU/UniXNU), with no checkout, Release downloads, secrets or scripts from any experiment repository. It produces a 64 MiB FAT32 volume with safe UEFI menu actions, embeds it into an Android boot-v4 image and publishes validated outputs in [Releases](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases). Verified images are always uploaded to **Actions Artifacts** (7-day retention), even if GitHub denies publishing a Release with HTTP 403. It does not run automatically on push.

**This public-only build does not contain an XNU kernel, ADT or iPadOS.** The stock UniXNU EFI application is integrated. The latest source adds an experimental, bounded read-only FAT32 lookup in the FDT initrd after a possible LZ4 Legacy vendor ramdisk. If the FAT is absent, UniXNU displays the DXE/initrd stage instead of only `no boot entry found`. This fix has not yet been verified on the tablet; the last tested public image predates it. The image must only be tried using an already tested temporary `fastboot boot` path, never flashed to Android partitions.

### Next public-source boot test

**Source fix (2026-10-27):** The manual build workflow now applies `ci/patch_sec_entry_hob.py` (save ABL/BootShim ARM64 entry `x0` through SEC, publish the UniXNU GUID HOB) and `ci/patch_public_buttons.py` (poll already-installed EFI SimpleTextIn handles without enabling experimental PMIC/SPMI drivers). Both patch scripts existed previously, but were accidentally omitted from the standalone build workflow. The last published build, [#40364858947](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/runs/40364858947), **does not contain either patch**. A newly dispatched build is needed.

In GitHub [Actions → Dizi standalone UEFI + UniXNU](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/build.yml), dispatch `main`, and download the resulting image from the newly created run. A successful new build will include `BOOT-PATCHES.txt` in its artifact and Release. That file records the source patches included, **not** proof of working buttons or a valid DTB on hardware. The workflow is manual-only and does not run on push.

For dizi devices whose fastboot boot path was **already confirmed working**, boot the downloaded `Mu-dizi-UNIXNU-PUBLIC-UEFI-NOT-FLASHABLE.img` temporarily, without `fastboot flash`:

```cmd
fastboot devices
fastboot boot Mu-dizi-UNIXNU-PUBLIC-UEFI-NOT-FLASHABLE.img
```

Record the full red `DIZI:` status text and test Volume Up, Volume Down and Power in the menu. `no-HOB` means the argument HOB is still absent; `bad-FDT` means it exists but `x0` is not recognized as a valid DTB; `LZ4-no-FAT` means the initrd was found but the bounded FAT32 lookup failed; `FAT-published-noFS` means read-only BlockIo published and further filesystem/device registration checks are needed. Avoid reboot/erase/flash actions in any unfamiliar menu. The build has **no XNU payload** and is not an Android/XNU dualboot image.

## Next milestones

1. Correctly expose a raw FAT32 payload to UniXNU across the LZ4/initrd handoff.
2. Load `EFI/UniXNU/unixnu.toml`, then verify XNU handoff and capture kernel logs.
3. Validate an SM7435 SoC source, firmware memory map, ADT and OS identity before enabling native builds.
4. Verify `ruan` independently.

Follow the [official device repository specification](https://unixnu.com/porting/device-repository) and [porting steps](https://unixnu.com/porting/steps). Do not flash experimental images into Android partitions.

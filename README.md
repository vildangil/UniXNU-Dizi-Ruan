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

The workflow uses **only public** pinned [Mu-Silicium](https://github.com/vildangil/Mu-Silicium) and [upstream UniXNU](https://github.com/UniXNU/UniXNU), with no checkout, Release downloads, secrets or scripts from any experiment repository. It produces a 64 MiB FAT32 volume with safe UEFI menu actions, embeds it into an Android boot-v4 image and publishes validated outputs in [Releases](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases). It does not use Actions Artifacts or run on push.

**This public-only build does not contain an XNU kernel, ADT or iPadOS.** The stock UniXNU EFI application is integrated, but this new combination is not yet hardware-verified and the original LZ4/initrd handoff issue remains. The image must only be tried using an already tested temporary `fastboot boot` path, never flashed to Android partitions.

## Next milestones

1. Correctly expose a raw FAT32 payload to UniXNU across the LZ4/initrd handoff.
2. Load `EFI/UniXNU/unixnu.toml`, then verify XNU handoff and capture kernel logs.
3. Validate an SM7435 SoC source, firmware memory map, ADT and OS identity before enabling native builds.
4. Verify `ruan` independently.

Follow the [official device repository specification](https://unixnu.com/porting/device-repository) and [porting steps](https://unixnu.com/porting/steps). Do not flash experimental images into Android partitions.

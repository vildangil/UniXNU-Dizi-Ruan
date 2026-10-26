# UniXNU Dizi / Ruan

Experimental [UniXNU](https://github.com/UniXNU/UniXNU) port for Xiaomi Redmi Pad Pro (`dizi`, Snapdragon SM7435). The `ruan` variant is not separately verified.

**Current stage:** EDK2 and the UniXNU graphical menu start on dizi using temporary `fastboot boot`. The payload is still not mounted: the FDT initrd buffer starts with LZ4 Legacy magic `0x184C2102`. XNU kernel entry, storage, GPU and iPadOS userland are not verified.

## Ownership

- **Device repository (this repo):** `board.toml`, defconfig, DTS, device evidence, eventual device drivers and boot profile.
- **[Mu-Silicium](https://github.com/vildangil/Mu-Silicium):** EDK2, BootShim, firmware configuration and PMIC/SPMI.
- **[UniXNU](https://github.com/UniXNU/UniXNU):** generic boot manager, DarwinBoot and shared components.

The checkout was initially derived from `UniXNU-sheng` (SM8550). Its drivers, MMIO values, firmware and iPadOS-specific settings must not be used on SM7435. Cleanup is required before native builds. The previous Dizi experiments and temporary images are in [dizi_IpadOS_maybe](https://github.com/vildangil/dizi_IpadOS_maybe).

## Building EDK2 on GitHub

Open [Actions → Dizi experimental EDK2 (GitHub-hosted)](https://github.com/vildangil/UniXNU-Dizi-Ruan/actions/workflows/build.yml), choose **Run workflow**, and select **main**. No self-hosted runner or additional repository secret is required.

The workflow installs the cross-compiler on GitHub's `ubuntu-24.04` runner, uses pinned Mu-Silicium and UniXNU sources, verifies the experimental boot-v4 image and publishes successful results to [Releases](https://github.com/vildangil/UniXNU-Dizi-Ruan/releases). It does not use Actions Artifacts, and it does not run automatically on push.

**This is only an EDK2/UniXNU firmware experiment, not a working native XNU or iPadOS image.** The image must only be tried using an already tested temporary `fastboot boot` path, never flashed to Android partitions.

## Next milestones

1. Correctly expose a raw FAT32 payload to UniXNU across the LZ4/initrd handoff.
2. Load `EFI/UniXNU/unixnu.toml`, then verify XNU handoff and capture kernel logs.
3. Validate an SM7435 SoC source, firmware memory map, ADT and OS identity before enabling native builds.
4. Verify `ruan` independently.

Follow the [official device repository specification](https://unixnu.com/porting/device-repository) and [porting steps](https://unixnu.com/porting/steps). Do not flash experimental images into Android partitions.

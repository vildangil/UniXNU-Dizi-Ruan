# UniXNU dizi

UniXNU device support for the Xiaomi Redmi Pad Pro, codename `dizi`
(Qualcomm SM7435, "Parrot"). The Redmi Pad Pro 5G (`ruan`) is not tested.

The board uses the [UniXNU-sm7435-common](https://github.com/vildangil/UniXNU-sm7435-common)
SoC profile, the iPadOS 17.7.11 (21H461) OS profile, and Mu-Silicium
[diziPkg](https://github.com/vildangil/Mu-Silicium/tree/main/Platforms/Xiaomi/diziPkg)
for UEFI.

## Status

Checked on a real dizi on 2026-11-14:

| Stage | State | Notes |
| --- | --- | --- |
| UEFI firmware and UniXNU menu | Works | Menu loads `\EFI\UniXNU\unixnu.toml` from the payload |
| Payload discovery | Works | Payload follows the LZ4 vendor ramdisk; UniXNURamDiskDxe skips it |
| Menu buttons | Not tested | PMIC key reader from the earlier build that worked; not yet tried on this build |
| DarwinBoot handoff | Works | Green bar drawn, ExitBootServices passes (KEP hook disabled) |
| XNU entry and MMU-on | Works | Blue and magenta probe bands; reset after MMU-on |
| `arm_init`, VM, IOKit, AMFI | Works | Needs the SoC virtual-timer patch and ADT `vmm-present = 1` |
| Root filesystem (UFS) | Partly | iPadOS root mounts read-only from `userdata` and launchd starts; dyld needs the SystemOS cryptex mounted |
| All 8 CPU cores | Works | `cpus=8 smp=1` |
| Boot-progress page | Works | Milestones, processes and console on screen (`boot-progress=1`) |
| Display driver, touch, Wi-Fi, audio, GPU | Not started | |

The next stage is mounting the SystemOS cryptex so launchd can load the dyld shared cache. [porting.toml](porting.toml) records every area with
its findings and evidence.

## Boot

The bootloader must be unlocked. `fastboot boot` starts the image once and
flashes nothing; a reboot returns to Android.

```sh
fastboot boot boot.img
```

The menu boots the UniXNU entry after 3 seconds. Volume keys move the
selection and Power confirms. Give Volume Down a firm press of about half a
second; a guard filters false PMIC presses.

## Reading the screen

| Screen | Meaning |
| --- | --- |
| Green band | DarwinBoot exited boot services and branched to XNU |
| Blue band | XNU entry code ran (MMU off) |
| Magenta band | XNU reached the MMU enable |
| White text under the bands | Kernel panic message and backtrace |

Hold Power to leave the panic screen.

## License

See [LICENSE](LICENSE).

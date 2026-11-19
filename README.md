# UniXNU dizi

UniXNU device support for the Xiaomi Redmi Pad Pro, codename `dizi`
(Qualcomm SM7435, "Parrot"). The Redmi Pad Pro 5G (`ruan`) is not tested.

The board uses the [UniXNU-sm7435-common](https://github.com/vildangil/UniXNU-sm7435-common)
SoC profile, the iPadOS 17.7.11 (21H461) OS profile, and Mu-Silicium
[diziPkg](https://github.com/vildangil/Mu-Silicium/tree/main/Platforms/Xiaomi/diziPkg)
for UEFI.

## Status

Checked on a real dizi on 2026-11-17:

| Stage | State | Notes |
| --- | --- | --- |
| UEFI firmware and UniXNU menu | Works | Menu loads `\EFI\UniXNU\unixnu.toml` from the payload |
| Payload discovery | Works | Payload follows the LZ4 vendor ramdisk; UniXNURamDiskDxe skips it |
| Menu buttons | Works | Volume Up, Volume Down and Power; hold each about one second |
| DarwinBoot handoff | Works | Green bar drawn, ExitBootServices passes (KEP hook disabled) |
| XNU entry and MMU-on | Works | Blue and magenta probe bands; reset after MMU-on |
| `arm_init`, VM, IOKit, AMFI | Works | Needs the SoC virtual-timer patch and ADT `vmm-present = 1` |
| Root filesystem (UFS) | Works | iPadOS OS and SystemOS volumes mount read-only from the `unixnu` partition |
| Data volume (`/private/var`) | Partly | Writable 128 MB volume in RAM; changes are lost on reboot |
| launchd, daemons, SpringBoard | Works | Lock screen with date, time and battery; SpringBoard stays up with the Data seed settings |
| Memory for XNU | Works | 256 MiB window plus the RAM above it (`memory-outside=3`, about 3.5 GiB more) |
| Dual boot with Android | Works | Android boots by default; a KernelSU Action boots iPadOS once from slot b |
| All 8 CPU cores | Works | `cpus=8 smp=1` |
| Boot-progress page | Works | Milestones, processes and console on screen (`boot-progress=1`) |
| Display | Works | backboardd draws through the GOP framebuffer (CPU copy); Apple logo and lock screen |
| Battery | Works | Level on the lock screen (PM7250B fuel gauge, from the ruan port) |
| Hardware buttons in iPadOS | Works | Power and volume keys (PMIC) |
| Touch | Works | NT36532 touch screen in iPadOS (the ruan port's driver, the tablet's own BOE firmware) |
| USB debug link | Partly | Kernel log over USB after `fastboot boot`; drops after a few minutes, and not available when booted from slot b |
| Wi-Fi, audio, GPU | Not started | |

The next stages are Volume Down in iPadOS, a stable USB debug link, and the ruan port's GPU work. [porting.toml](porting.toml) records every
area with its findings and evidence.

## Boot

The bootloader must be unlocked. `fastboot boot` starts the image once and
flashes nothing; a reboot returns to Android.

```sh
fastboot boot boot.img
```

The menu boots the UniXNU entry after 3 seconds. Volume keys move the
selection and Power confirms. Hold each button about one second; the PMIC key
reader samples slowly and filters false presses.

### Partitions

The original `userdata` partition (110 GB) is split in two, so Android and iPadOS each keep their own:

| GPT entry | Name | Size | Holds |
| --- | --- | --- | --- |
| 22 | `unixnu` | 32 GiB | iPadOS 17.7.11 `OS` and `SystemOS` volumes (8.74 GiB, read only) |
| 21 | `userdata` | 70.9 GiB | Android data (F2FS) |

`unixnu` starts where the old `userdata` started (LBA 0x35a228); `userdata` keeps its original GUIDs. Repartitioning
needs a recovery with `sgdisk` and erases Android's data; back up both partition tables first. Flash the iPadOS root
to `unixnu`, never to `userdata`:

```sh
fastboot flash unixnu userdata-root.img
fastboot boot boot.img
```

Flashing takes about half an hour over USB.

### Dual boot

Android stays on slot a and boots by default. iPadOS boots once from slot b:

| Partition | Holds |
| --- | --- |
| `boot_b` | The UniXNU image (Mu-Silicium UEFI and the payload) |
| Other slot-b partitions | The same firmware as slot a |
| `vbmeta_b` | Verification turned off |

The `UniXNU dual boot` KernelSU module ([dualboot/ksu-module](dualboot/ksu-module)) has an Action button. It
checks that `boot_b` holds UniXNU, makes slot b active through the boot control HAL, and gives `boot_b` one retry
without marking it successful. The bootloader boots iPadOS once; on the next reboot it marks slot b unbootable and
switches back to Android by itself.

Android needs root (KernelSU) for the button. The module bundles AOSP's `bootctl`, which HyperOS does not ship.
Something that copies `boot_a` to the inactive slot (for example after an OTA) replaces UniXNU in `boot_b`; the
button then refuses to switch until UniXNU is written back.

The recovery key cannot start UniXNU: the bootloader drops to fastboot for a `recovery_a` image that carries its own
kernel.

## Reading the screen

With `boot-progress=1` the kernel draws a status page:

| Part | Meaning |
| --- | --- |
| Top line | `t=` seconds since boot, `irq=` interrupts, `procs`/`exec`/`exit` counts, `mem=` RAM for XNU |
| Milestone boxes | KERNEL, VM, SCREEN, SCHED, IOKIT, BSD, ROOTFS, LAUNCHD, DAEMONS, BACKBOARD, SPRINGBOARD; grey not reached, green reached, yellow the latest, red failed |
| Events | Kernel stages, PID 1 system calls that failed, launchd output |
| Processes | Every started process: green running, grey exited 0, red failed, yellow signature refused |
| Console | The kernel log |

Without the page, the early boot shows coloured bands:

| Screen | Meaning |
| --- | --- |
| Green band | DarwinBoot exited boot services and branched to XNU |
| Blue band | XNU entry code ran (MMU off) |
| Magenta band | XNU reached the MMU enable |
| White text under the bands | Kernel panic message and backtrace |

Hold Power to leave a panic screen. If DarwinBoot shows `NO WINDOW … Out of
Resources`, the requested memory window does not fit dizi's UEFI memory map.

## License

See [LICENSE](LICENSE).

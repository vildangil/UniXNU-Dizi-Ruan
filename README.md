# UniXNU dizi

UniXNU device support for the Xiaomi Redmi Pad Pro, codename `dizi`
(Qualcomm SM7435, "Parrot"). The Redmi Pad Pro 5G (`ruan`) is not tested.

The board uses the [UniXNU-sm7435-common](https://github.com/vildangil/UniXNU-sm7435-common)
SoC profile, the iPadOS 17.7.11 (21H461) OS profile, and Mu-Silicium
[diziPkg](https://github.com/vildangil/Mu-Silicium/tree/main/Platforms/Xiaomi/diziPkg)
for UEFI.

## Status

Checked on a real dizi on 2026-11-14, booted once with `fastboot boot`:

| Stage | State | Notes |
| --- | --- | --- |
| UEFI firmware and UniXNU menu | Works | Menu loads `\EFI\UniXNU\unixnu.toml` from the payload |
| Payload discovery | Works | Payload follows the LZ4 vendor ramdisk; UniXNURamDiskDxe skips it |
| Menu buttons | Partly | PMIC key reader from the old-ChatGPT build; Volume Down retuned, not re-tested |
| DarwinBoot handoff | Works | Green bar drawn, ExitBootServices passes (KEP hook disabled) |
| XNU entry and MMU-on | Works | Blue and magenta probe bands; reset after MMU-on |
| `arm_init`, VM, IOKit, AMFI | Works | Needs the SoC virtual-timer patch and ADT `vmm-present = 1` |
| Root filesystem | Missing | Stops at `Failed to mount root device` (IOKitBSDInit.cpp:984) |
| Secondary CPUs | Not tested | `cpus=1` is the default |
| Storage, display driver, touch, Wi-Fi, audio, GPU | Not started | |

The root filesystem is the next stage: a storage driver for dizi's UFS and
an iPadOS root image (`unixnu build userdata`). [porting.toml](porting.toml)
records every area with its findings and evidence.

## Repositories

Clone all four side by side (the build expects these folder names):

```sh
git clone --recurse-submodules https://github.com/UniXNU/UniXNU
git clone https://github.com/vildangil/UniXNU-Dizi-Ruan
git clone https://github.com/vildangil/UniXNU-sm7435-common
git clone --recurse-submodules https://github.com/vildangil/Mu-Silicium
```

| Repository | Contents |
| --- | --- |
| UniXNU-Dizi-Ruan (this) | `board.toml`, `configs/dizi_defconfig`, `dts/dizi.dts`, `porting.toml` |
| UniXNU-sm7435-common | SoC DTSI, config fragment and XNU patches (SMP, virtual timer) |
| Mu-Silicium | UEFI for dizi, SEC FDT handoff, dizi menu keys (`diziPkg/Library/UniXNULibDizi`) |
| UniXNU | Build tool, components, OS profiles |

UniXNU upstream does not yet have three fixes this port needs: the LZ4
payload skip in `UniXNURamDiskDxe`, NOP padding in `patch-xnu-entry-probe.py`
and `-Wno-unknown-warning-option` for Xcode 26.3. They are on a local
`dizi-bringup` branch of UniXNU until they are upstreamed or forked.

## Build on macOS

Requirements: Xcode (26.3 tested), [MacPorts](https://www.macports.org) and a
path without spaces. Do not use Homebrew.

```sh
sudo port install python314 llvm-20 dtc mtools ninja cmake android-platform-tools
```

UniXNU's scripts call `python3` and need Python 3.11 or newer. If `python3`
is the system 3.9, put a link to MacPorts Python first in `PATH`:

```sh
mkdir -p ~/dizi-work/.bin && ln -sf /opt/local/bin/python3.14 ~/dizi-work/.bin/python3
export PATH=~/dizi-work/.bin:/opt/local/libexec/llvm-20/bin:/opt/local/bin:$PATH
```

Local inputs stay out of Git:

- `UniXNU/unixnu.local.toml` sets `device`, `uefi`, `dtb`, `trust_cache` and
  `unique_chip_id`. The chip ID is a random nonzero 8-digit hex seed
  (`openssl rand -hex 4`). Keep it the same for every build of one tablet;
  it is that tablet's identity to iPadOS.
- `UniXNU-Dizi-Ruan/local.toml` can point the SoC feed at a local
  UniXNU-sm7435-common checkout while you change it.

Build everything from the UniXNU checkout:

```sh
cd UniXNU
./unixnu defconfig dizi_defconfig -D ../UniXNU-Dizi-Ruan
./unixnu fetch
./unixnu build kernel
./unixnu build firmware --uefi ../Mu-Silicium
./unixnu ipsw fetch
python3 scripts/bundle-ipsw-trust.py out/dizi/ipados-17.7.11-21H461/dizi/trust/ipsw-trust.bundle \
  out/ipsw/21H461/044-76040-038.dmg.trustcache out/ipsw/21H461/044-76034-038.dmg.trustcache
./unixnu build payload
./unixnu bootimg
```

The boot image is `out/dizi/ipados-17.7.11-21H461/dizi/boot/boot.img`
(about 58 MiB; the boot partition is 100 MiB). The trust bundle's SHA-256
must be `7416ca4f…`, the value the iPadOS 17 profile allows.

## Boot

The bootloader must be unlocked. `fastboot boot` starts the image once and
flashes nothing; a reboot returns to Android.

```sh
fastboot getvar product      # must print dizi
fastboot boot out/dizi/ipados-17.7.11-21H461/dizi/boot/boot.img
```

The menu boots the UniXNU entry after 3 seconds. Volume keys move the
selection and Power confirms. Give Volume Down a firm press of about half a
second; a guard filters false PMIC presses.

## Reading the screen

The payload enables UniXNU's entry probe and panic screen
([debugging guide](https://unixnu.com/guide/debugging)):

| Screen | Meaning |
| --- | --- |
| Green band | DarwinBoot exited boot services and branched to XNU |
| Blue band | XNU entry code ran (MMU off) |
| Magenta band | XNU reached the MMU enable |
| White text under the bands | Kernel panic message and backtrace |

Resolve backtrace addresses against
`out/dizi/ipados-17.7.11-21H461/dizi/kernel/kernel.macho` with
`llvm-symbolizer`. Hold Power to leave the panic screen.

## Files inherited from sheng

This repository started as a fork of
[UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng). These parts are
still sheng's and are not used by `dizi_defconfig`: the `sheng_*`
defconfigs, `drivers/`, `firmware/`, `hal/`, most of `package/` and
`scripts/`, `patches/xnu/zzy*`, `patches/xnu-12377/` and
`.github/workflows/package.yml`. `build-kernel.yml` and
`porting-record.yml` are set up for dizi.

## License

See [LICENSE](LICENSE).

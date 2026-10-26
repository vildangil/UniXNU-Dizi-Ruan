# UniXNU Dizi/Ruan development rules

This is a UniXNU device repository for Xiaomi Redmi Pad Pro `dizi`,
Qualcomm `SM7435`. The `ruan` variant needs separate hardware validation.

Follow https://unixnu.com/porting/device-repository and
https://unixnu.com/porting/records.

- Device-specific profile, DTS, XNU patches, evidence and kits belong here.
- EDK2, SEC/BDS, BootShim, PMIC/SPMI and firmware modules belong in
  https://github.com/vildangil/Mu-Silicium.
- Generic EFI/XNU support belongs in upstream UniXNU.
- Never use sheng/SM8550 drivers, MMIO/IRQ values, storage geometry,
  firmware blobs or iPadOS identity as evidence of SM7435 support.
- Do not enable kernel builds until SoC source, IPSW/ADT identity, memory
  and DTB inputs have been reviewed. Keep `board.example = true` until then.
- Separate source preflight, successful firmware build, EFI menu boot, FAT
  mount, XNU entry, storage and userland into distinct verified checkpoints.
- Do not commit generated images, vendor firmware or secrets.
- GitHub-hosted `ubuntu-24.04` is used for both static checks and the
  pinned experimental EDK2 build. The build runs on manual dispatch only,
  with no automatic push builds or Actions Artifacts.
- Do not flash experimental images into Android partitions.

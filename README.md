# UniXNU dizi / ruan

Device support for the Xiaomi Redmi Pad Pro (Wi-Fi `dizi`) and Redmi Pad Pro 5G (`ruan`), Qualcomm SM7435. This repository follows the UniXNU device repository format: board configuration, kernel defconfig, device scripts, drivers, and packaging for the `dizi`/`ruan` platform.

> **Status: work in progress.** No fully verified UniXNU/XNU operating system is available for `dizi` or `ruan` yet. The current focus is diagnostic bring-up of the early boot path, specifically framebuffer aliasing and native TTBR1 replacement. See [Release channels](docs/DIZI-RELEASE-CHANNELS.md) for the exact distinction between STABLE and DEV BETA.

## Device

| Item | Value |
|---|---|
| Codename | `dizi` (Wi-Fi), `ruan` (5G) |
| SoC | Qualcomm SM7435 |
| Target OS profiles | iOS / iPadOS userland (early bring-up) |
| Current milestone | FB8 readback diagnostics before native TTBR1 switch |

## Repositories

| Repository | Contents |
|---|---|
| [UniXNU](https://github.com/UniXNU/UniXNU) | Build driver, component catalog, ARM64 support, OS profiles, UEFI package |
| **UniXNU-Dizi-Ruan** (this repo) | Board configuration, defconfig, scripts, device-specific drivers and packaging for `dizi`/`ruan` |
| `uefi-dizi` (companion) | UEFI firmware for the `dizi` platform (clone alongside this repository) |

Clone with submodules where applicable:

```sh
git clone --recurse-submodules https://github.com/UniXNU/UniXNU
git clone --recurse-submodules https://github.com/vildangil/UniXNU-Dizi-Ruan
```

## Build

Follow the standard UniXNU device build flow. This repository is consumed as the device repository (`-D` argument) from the main `UniXNU` checkout.

Typical sequence from the `UniXNU` directory:

```sh
./unixnu defconfig <dizi_defconfig> -D ../UniXNU-Dizi-Ruan
./unixnu status --json -D ../UniXNU-Dizi-Ruan
./unixnu build firmware --uefi ../uefi-dizi
./unixnu build payload -D ../UniXNU-Dizi-Ruan
```

Build outputs and exact variant names are documented in [Build and boot](https://unixnu.com/building) and in the release-channel policy of this repository.

## Testing and safety

- **Only temporary `fastboot boot` is permitted.** Never `fastboot flash` a DEV BETA image. Flashing an unverified boot image can leave the device unbootable.
- **STABLE does not exist.** Any image labelled otherwise is not a verified stable build.
- **DEV BETA images may not boot.** That is expected during bring-up. Diagnostic images such as `fb8-readback-b` are **read-only by design** and stop before page-table writes or native TTBR1 switch.

## Diagnostics

The current diagnostic focus is the framebuffer alias and TTBR1 handoff. The relevant documents are:

- [Release channels](docs/DIZI-RELEASE-CHANNELS.md) — STABLE vs DEV BETA policy
- [FB8 readback](docs/DIZI-FB8-READBACK-B.md) — readback-only diagnostic and expected SHA-256
- [FB bridge B](docs/DIZI-FB-BRIDGE-B.md) — framebuffer alias preservation experiment (high risk, manual only)
- [Stack-B](docs/DIZI-STACK-B.md) — active-stack/data walk readbacks
- [Leaf-B](docs/DIZI-LEAF-B.md) — code-page PTE readbacks

All device results, photos, serial logs and SHA-256 checks belong in the linked documents, not in this README. Keep this page as a stable entry point.

## Contributing

Maintain the porting record with every subsystem change, following the same guide as other UniXNU device repositories: [Porting records](https://unixnu.com/porting/records). CI validates structure, component coverage and evidence updates. For this repository specifically, use the control PR and owner-triggered diagnostic workflows described in the release-channel policy.

## License

BSD-2-Clause-Patent. See [LICENSE](LICENSE).
```

---

Что я изменил по сравнению с твоим текущим README, в стиле оригинального UniXNU:

- **Убрал хронологию** (даты, «latest device result», повторяющиеся упоминания одних и тех же экспериментов). В UniXNU-sheng такого нет — там есть `porting.toml` и отдельные документы для записи результатов.
- **Оставил жёсткие предупреждения** про `fastboot boot` / never flash и отсутствие STABLE — это критично и должно быть в README.
- **Добавил таблицу Device и Repositories**, как в оригинале и в `sheng`.
- **Сделал раздел Build** со стандартными командами, а не с описанием каждого варианта сборки.
- **Вынес всю диагностику в отдельные `docs/`**, оставив только ссылки — именно так устроены нормальные device repos UniXNU.

Если хочешь, могу следующим шагом привести `docs/` к такому же стилю — например, сделать `docs/DIZI-RELEASE-CHANNELS.md` и `docs/DIZI-FB8-READBACK-B.md` компактными и единообразными, без дублирования хронологии из README.

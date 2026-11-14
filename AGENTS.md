# Agent instructions

This repository owns the dizi (Xiaomi Redmi Pad Pro, SM7435) board
configuration, peripherals, firmware selection, partition layout, power
policy, and packaging. Shared SM7435 resources and XNU patches belong to
`UniXNU-sm7435-common`. UEFI for dizi lives in Mu-Silicium `diziPkg`. The
documentation site, component catalog, and common build tools belong to
`UniXNU`.

Do not copy SM8550 (sheng) addresses, clocks, GPU, SMMU, UFS or power values
into dizi. Files still named `sheng*` are leftovers from the fork; the README
lists them. They are not dizi support.

Read the following before editing:

| Task | Required reading |
| --- | --- |
| Every port | [Porting](https://unixnu.com/porting/), [repository format](https://unixnu.com/porting/device-repository), [component catalog](https://unixnu.com/reference/components) |
| Hardware | [Device trees](https://unixnu.com/porting/device-tree), [matching](https://unixnu.com/drivers/device-tree-matching), selected SoC README and DTSI |
| Components | Selected component README, catalog metadata, build interface, relevant source |
| Kernel | Selected OS profile, XNU source, [patch reference](https://unixnu.com/xnu/source-and-patches), ordered patch series |
| Images | [Prelink](https://unixnu.com/concepts/prelink), [payload](https://unixnu.com/concepts/payload), [UEFI firmware](https://unixnu.com/porting/uefi-firmware) |
| Verification | [Building](https://unixnu.com/building), [bring-up](https://unixnu.com/porting/bring-up) |
| Migration | [Migration guide](https://unixnu.com/porting/migration) |

Search UniXNU's `components.toml` and read existing implementations before
adding a capability. Select components by interface, hardware scope, OS
ABI, and board dependencies. Use canonical component names in sources,
paths, build commands, and dependencies. Preserve source filenames,
runtime classes, bundle IDs, plugin filenames, symbols, and protocol IDs.

Use `dts/dizi.dts` for board hardware; it includes `sm7435.dtsi` from the
SoC repository. UniXNU's ADT generator needs a single contiguous memory
range. Inspect `local.toml` and CLI overrides before changing source pins.
After changing UniXNU-sm7435-common, push it and update the commit in
`feeds.toml` and `unixnu.lock` together.

Run from the UniXNU checkout:

```sh
./unixnu defconfig dizi_defconfig --device ../UniXNU-Dizi-Ruan
./unixnu status --device ../UniXNU-Dizi-Ruan --json
./unixnu tree --device ../UniXNU-Dizi-Ruan
./unixnu build kernel --device ../UniXNU-Dizi-Ruan
```

Only boot test images with `fastboot boot`; do not flash partitions
without the owner's approval. Run existing checks
relevant to the change, including
`python3 scripts/porting-record.py check --device ../UniXNU-Dizi-Ruan`
from UniXNU. Report commands, outputs, missing inputs, and
hardware observations separately. Record device boot, storage, display,
input, and GPU checkpoints.

Update relevant English and Chinese site pages in UniXNU. Write concise
English for this repository. Describe current behavior with direct
statements and ordinary punctuation.

## Porting record

Read the device's `porting.toml` and the
[record guide](https://unixnu.com/porting/records) before implementation.
For storage, also read the [UFS guide](https://unixnu.com/porting/ufs).
Update each affected area's findings or evidence with its code change.
The documentation site renders this same record. Follow its schema and
completion levels for both maintainer and agent work.

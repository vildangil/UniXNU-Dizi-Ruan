# Archived references for removed one-off Dizi diagnostic tags (2026-10-29)

This list captures the **exact Git commit SHAs** of 23 historic tags that
do not have a corresponding GitHub Release. After cleanup, these commits
remain in repository history and can be opened by SHA; the unneeded tag
names are removed from the GitHub **Tags** tab.

The 11 tags associated with existing GitHub Releases are **excluded** from
deletion, including the mutable test release `dizi-xnu-latest-test` and
the immutable `dizi-xnu-five-nosp-base` used by the manual MMU workflow.
No release assets, kernel images, branches, commits, or workflow logs should
be deleted by this cleanup.

## Tags to remove (SHA backup)

| Obsolete tag | Original commit SHA |
| --- | --- |
| `dizi-public-uefi-40342440746-1` | `8fba1a189141c02ff94aae550d6cfc37cd30b0d9` |
| `dizi-public-uefi-40358544404-1` | `7af61c0fdb32f275d9fabc62fac784b9172ab16e` |
| `dizi-public-uefi-40364858947-1` | `29010f35a8d93e123bd999a73f42236ab3283d83` |
| `dizi-public-uefi-40455314618-1` | `d62095a66cc945505b66547d51586354a1793cc1` |
| `dizi-public-uefi-40455830003-1` | `d7b5944811d9d51e1d0311e5539d8869b0704728` |
| `dizi-public-uefi-40487237658-1` | `3593bff3cc551f6b788d83d93b2eaf88a50a6b3d` |
| `dizi-public-uefi-40534403345-1` | `986ea2a6705c56df99659b2bc199c6fd9ead1cec` |
| `dizi-xnu-adt-parse-probe-40560506106-1` | `064da7114b9de2279642d5c720c7861526f9e2ab` |
| `dizi-xnu-adt-parse-probe-40562998521-1` | `4cabaeda114db3b389ee861f0ff514f76fa00134` |
| `dizi-xnu-dxe-ebs-40582370738-1` | `c116f73216df86e10a1d7ed351bffdf5515115d6` |
| `dizi-xnu-ebs-boundary-40579965947-1` | `4ce812c2d6bb3af3a72bfab59d97fc08db0f3aa5` |
| `dizi-xnu-ebs-core-pointer-40633998662-1` | `e87f9be1296471c3dc4baed7a66086de7767b697` |
| `dizi-xnu-ebs-core-trace-40630906639-1` | `5508f6535ee12e7aeee74ef1efa909669f6174ec` |
| `dizi-xnu-ebs-fb-fixed-40637451443-1` | `e0d084de440bc467349ae321ca8324773fc069f7` |
| `dizi-xnu-ebs-four-words-40639206923-1` | `ed2925615f68a6b24636155e4493bc214540c042` |
| `dizi-xnu-ebs-opcode-40637202770-1` | `a1f2b38d8554d0697548138d4caea2c44201d55e` |
| `dizi-xnu-ebs-toptiles-40635399461-1` | `55dd016ea03ba7a2c3025a91e9e1c767a680d514` |
| `dizi-xnu-first-entry-40577187959-1` | `9be95e4a2910365252754225bdb497b934934abd` |
| `dizi-xnu-first-entry-no-kep-40642424939-1` | `6aa516e26bf8046233727ce7a6b1d87fe4d1b7ae` |
| `dizi-xnu-loader-probe-40557234402-1` | `6f158b7f048d1af3779e372adc446d92fc011d17` |
| `dizi-xnu-native-start-no-kep-40644853194-1` | `5198993a244baa550998a1187e0f9d2825ee63c3` |
| `dizi-xnu-pre-mmu-no-kep-40646191965-1` | `cbe8a21fd7a41d748b556eebcc5497e8bacf9aaf` |
| `dizi-xnu-window-probe-40570339452-1` | `c6735defb805d2c361539cb6189bcd753554845c` |

## Current protected release tags

- `dizi-public-uefi-40544976346-1`
- `dizi-xnu-bootstrap-stages-40647473480-1`
- `dizi-xnu-ebs-no-kep-40641321399-1`
- `dizi-xnu-first-opcode-no-kep-40643799207-1`
- `dizi-xnu-five-nosp-base`
- `dizi-xnu-latest-test`
- `dizi-xnu-mmu-first-nosp-40700727875-1`
- `dizi-xnu-mmu-reg-stages-40649020254-1`
- `dizi-xnu-mmu-stackless-40700771901-1`
- `dizi-xnu-prelinked-window-probe-40574804304-1`
- `dizi-xnu-source-40552223877`

## Procedure and safeguards

One-time GitHub Actions job verifies every tag name and exact object SHA,
checks that none is associated with a release, and rejects changed refs
before deletion. It runs only upon this archive document being added to
`main` (or manual dispatch). No wildcard deletion, no `git push --force`,
and no release deletion. If it fails, inspect the Actions log before retry.

The job should be removed from the active workflow directory after
successful execution so no unnecessary workflow remains.

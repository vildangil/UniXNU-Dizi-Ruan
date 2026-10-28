#!/usr/bin/env bash
# Publish exactly ONE rolling, high-risk boot.img. Full diagnostics stay
# in GitHub Actions Artifacts; do not create a new tag per CI run.
set -euo pipefail
if [[ $# -ne 1 || -z "${GH_TOKEN:-}" || -z "${GITHUB_REPOSITORY:-}" ]]; then
  echo "Usage: GH_TOKEN=... GITHUB_REPOSITORY=... $0 dist/<boot>.img" >&2
  exit 2
fi
src="$1"
if [[ ! -s "$src" || "$src" != dist/*.img ]]; then
  echo "Refusing to publish a missing/non-dist boot image: $src" >&2
  exit 2
fi
if [[ "$(head -c 8 "$src")" != "ANDROID!" ]]; then
  echo "Not an Android boot image: $src" >&2
  exit 2
fi
tag="dizi-xnu-latest-test"
source_run="${DIZI_SOURCE_RUN_ID:-$GITHUB_RUN_ID}"
asset="dist/Mu-dizi-XNU-LATEST-TEST.img"
cp -- "$src" "$asset"
sha="$(sha256sum "$asset" | cut -d' ' -f1)"
printf '%s  %s\n' "$sha" "$asset"
notes="$(mktemp)"
trap 'rm -f "$notes"' EXIT
cat > "$notes" <<EOF
## Dizi / UniXNU latest experimental test (HIGH RISK)

**Temporary fastboot boot ONLY. NEVER fastboot flash.**
The experimental XNU handoff can hang, reboot, or damage user data.
Back up device and maintain recovery access before testing.

- Source build: https://github.com/${GITHUB_REPOSITORY}/actions/runs/${source_run}
- Source boot image: $(basename "$src")
- Single downloadable asset: $(basename "$asset")
- SHA-256: ${sha}
- Full diagnostic binaries (UEFI .fd, FAT .fat, maps, JSON): **Actions Artifacts** of the source run (retained according to its workflow policy).
- Kernel boot success is **not** established by successful CI.
EOF
if gh release view "$tag" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  # Replacing one constant asset name does not create 3 redundant images
  # or a new prerelease on every run.
  gh release upload "$tag" "$asset" --repo "$GITHUB_REPOSITORY" --clobber
  gh release edit "$tag" --repo "$GITHUB_REPOSITORY" --prerelease \
    --title "Dizi UniXNU LATEST high-risk boot.img (run ${source_run})" \
    --notes-file "$notes"
else
  gh release create "$tag" "$asset" --repo "$GITHUB_REPOSITORY" \
    --target "$GITHUB_SHA" --prerelease \
    --title "Dizi UniXNU LATEST high-risk boot.img (run ${source_run})" \
    --notes-file "$notes"
fi
echo "Rolling test release (one IMG only): https://github.com/${GITHUB_REPOSITORY}/releases/tag/${tag}"

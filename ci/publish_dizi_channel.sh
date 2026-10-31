#!/usr/bin/env bash
# Only DEV BETA may be published before XNU boots fully on actual dizi hardware.
# A future STABLE requires proven full-OS boot and a separate owner-approved workflow.
# No push / PR triggers. Temporary fastboot boot ONLY; NEVER fastboot flash.
set -euo pipefail
if [[ $# -ne 2 || -z "$GH_TOKEN" || -z "$GITHUB_REPOSITORY" ]]; then
  echo "Usage: GH_TOKEN=... GITHUB_REPOSITORY=... $0 dev dist/<boot>.img" >&2; exit 2
fi
channel="$1"
src="$2"
if [[ "$channel" != dev ]]; then
  echo "STABLE is prohibited: full XNU OS boot not hardware-confirmed. Only dev beta is permitted." >&2
  exit 2
fi
if [[ ! -s "$src" || "$src" != dist/*.img ]]; then
  echo "Refusing missing or non-dist image: $src" >&2; exit 2
fi
if [[ "$(head -c 8 "$src")" != "ANDROID!" ]]; then
  echo "Not an Android boot image: $src" >&2; exit 2
fi
if [[ "$GITHUB_REPOSITORY" != "vildangil/UniXNU-Dizi-Ruan" ]]; then
  echo "Refusing another repository" >&2; exit 2
fi
tag=dizi-xnu-dev-beta
asset_name=Mu-dizi-XNU-DEV-BETA.img
title="Dizi DEV BETA - latest high-risk diagnostic"
digest="$(sha256sum "$src" | cut -d' ' -f1)"
target="dist/$asset_name"
if [[ "$target" != "$src" ]]; then cp -- "$src" "$target"; fi
echo "$digest  $target" | sha256sum --check
source_run="$GITHUB_RUN_ID"
if [[ -v DIZI_SOURCE_RUN_ID ]]; then source_run="$DIZI_SOURCE_RUN_ID"; fi
notes="$(mktemp)"
trap 'rm -f "$notes"' EXIT
cat > "$notes" <<EOF
# Dizi DEV BETA — experimental boot image (NOT stable)
HIGH RISK: this is an early diagnostic, not a functioning XNU operating system.
It can fail, hang or reset. Temporary fastboot boot ONLY; NEVER fastboot flash.
Back up and maintain recovery access.
Source Actions run: https://github.com/$GITHUB_REPOSITORY/actions/runs/$source_run
Selected image: $(basename "$src")
Published asset: $asset_name
SHA-256: $digest
The full build reports remain in the source Actions artifact.
The release is replaced only on the next owner-authorized manual build.
EOF
if gh release view "$tag" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
  gh release upload "$tag" "$target" --repo "$GITHUB_REPOSITORY" --clobber
  gh release edit "$tag" --repo "$GITHUB_REPOSITORY" --prerelease \
    --title "$title" --notes-file "$notes"
else
  gh release create "$tag" "$target" --repo "$GITHUB_REPOSITORY" \
    --target "$GITHUB_SHA" --prerelease --title "$title" --notes-file "$notes"
fi
count="$(gh release view "$tag" --repo "$GITHUB_REPOSITORY" --json assets --jq '.assets | length')"
if [[ "$count" != 1 ]]; then echo "Expected exactly one DEV BETA asset; got $count" >&2; exit 1; fi
echo "DEV BETA published: https://github.com/$GITHUB_REPOSITORY/releases/tag/$tag"

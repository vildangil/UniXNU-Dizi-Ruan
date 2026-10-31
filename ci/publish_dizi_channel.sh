#!/usr/bin/env bash
# Owner-manual channels: immutable hardware-observed STABLE checkpoint and rolling DEV BETA.
set -euo pipefail
if [[ $# -ne 2 || -z "$GH_TOKEN" || -z "$GITHUB_REPOSITORY" ]]; then
  echo "Usage: GH_TOKEN=... GITHUB_REPOSITORY=... $0 stable|dev dist/<boot>.img" >&2; exit 2
fi
channel="$1"
src="$2"
if [[ ! -s "$src" || "$src" != dist/*.img ]]; then
  echo "Refusing missing/non-dist image: $src" >&2; exit 2
fi
if [[ "$(head -c 8 "$src")" != "ANDROID!" ]]; then
  echo "Not an Android boot image: $src" >&2; exit 2
fi
if [[ "$GITHUB_REPOSITORY" != "vildangil/UniXNU-Dizi-Ruan" ]]; then
  echo "Refusing another repository" >&2; exit 2
fi
case "$channel" in
  stable)
    tag="dizi-xnu-stable"
    asset_name="Mu-dizi-XNU-STABLE.img"
    title="Dizi STABLE reference - first NO-SP checkpoint (NOT OS boot)"
    expected="ceb970d09e05aeff9e09293528d6193a87bf760c96a6e222766df6e73e249620"
    ;;
  dev)
    tag="dizi-xnu-dev-beta"
    asset_name="Mu-dizi-XNU-DEV-BETA.img"
    title="Dizi DEV BETA - latest high-risk diagnostic"
    ;;
  *) echo "Unknown channel: $channel" >&2; exit 2 ;;
esac
digest="$(sha256sum "$src" | cut -d' ' -f1)"
if [[ "$channel" == "stable" && "$digest" != "$expected" ]]; then
  echo "STABLE must be the exact observed first-NOSP control" >&2; exit 1
fi
target="dist/$asset_name"
if [[ "$target" != "$src" ]]; then cp -- "$src" "$target"; fi
echo "$digest  $target" | sha256sum --check
source_run="$GITHUB_RUN_ID"
if [[ -v DIZI_SOURCE_RUN_ID ]]; then source_run="$DIZI_SOURCE_RUN_ID"; fi
notes="$(mktemp)"
trap 'rm -f "$notes"' EXIT
if [[ "$channel" == "stable" ]]; then
  cat > "$notes" <<EOF
# STABLE reference checkpoint (not an operating system)
Physically observed first NO-SP / XNU-entry milestone. This is NOT a fully booted XNU OS.
SHA-256 (immutable): $digest
Source run: https://github.com/$GITHUB_REPOSITORY/actions/runs/$source_run
Source release: https://github.com/$GITHUB_REPOSITORY/releases/tag/dizi-xnu-mmu-first-nosp-40700727875-1
Published asset: $asset_name
HIGH RISK: temporary fastboot boot only; NEVER fastboot flash.
EOF
  if gh release view "$tag" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    echo "STABLE already exists; immutable release will not be changed" >&2; exit 1
  fi
  gh release create "$tag" "$target" --repo "$GITHUB_REPOSITORY" \
    --target "$GITHUB_SHA" --latest=false --title "$title" --notes-file "$notes"
else
  cat > "$notes" <<EOF
# DEV BETA - experimental boot image (NOT stable)
HIGH RISK. This is an early diagnostic, not a functioning OS.
Temporary fastboot boot ONLY; NEVER fastboot flash. Back up and keep recovery available.
Source Actions run: https://github.com/$GITHUB_REPOSITORY/actions/runs/$source_run
Source image: $(basename "$src")
Published asset: $asset_name
SHA-256: $digest
Full build audits remain as Actions artifacts. This rolling release is overwritten by the next owner-authorized manual publish.
EOF
  if gh release view "$tag" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    gh release upload "$tag" "$target" --repo "$GITHUB_REPOSITORY" --clobber
    gh release edit "$tag" --repo "$GITHUB_REPOSITORY" --prerelease \
      --title "$title" --notes-file "$notes"
  else
    gh release create "$tag" "$target" --repo "$GITHUB_REPOSITORY" \
      --target "$GITHUB_SHA" --prerelease --title "$title" --notes-file "$notes"
  fi
fi
count="$(gh release view "$tag" --repo "$GITHUB_REPOSITORY" --json assets --jq '.assets | length')"
if [[ "$count" != 1 ]]; then echo "Expected exactly one asset; got $count" >&2; exit 1; fi
echo "$channel published: https://github.com/$GITHUB_REPOSITORY/releases/tag/$tag"

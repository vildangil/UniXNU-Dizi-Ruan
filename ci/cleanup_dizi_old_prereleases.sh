#!/usr/bin/env bash
# Explicit, one-time cleanup of old EXPERIMENTAL pre-releases only.
# This deliberately preserves 9 control/known-good releases, all source,
# all git commits, all branches, and the working EDK2.
set -euo pipefail
: "${GH_TOKEN:?GH_TOKEN required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY required}"
if [[ "$GITHUB_REPOSITORY" != "vildangil/UniXNU-Dizi-Ruan" ]]; then
  echo "Wrong repository" >&2; exit 2
fi

# Literal, reviewed allowlist; never use wildcard deletion against releases.
obsolete=(
  dizi-xnu-pre-mmu-no-kep-40646191965-1
  dizi-xnu-native-start-no-kep-40644853194-1
  dizi-xnu-first-entry-no-kep-40642424939-1
  dizi-xnu-ebs-toptiles-40635399461-1
  dizi-xnu-ebs-opcode-40637202770-1
  dizi-xnu-ebs-four-words-40639206923-1
  dizi-xnu-ebs-fb-fixed-40637451443-1
  dizi-xnu-ebs-core-trace-40630906639-1
  dizi-xnu-ebs-core-pointer-40633998662-1
  dizi-xnu-window-probe-40570339452-1
  dizi-xnu-loader-probe-40557234402-1
  dizi-xnu-first-entry-40577187959-1
  dizi-xnu-ebs-boundary-40579965947-1
  dizi-xnu-dxe-ebs-40582370738-1
  dizi-xnu-adt-parse-probe-40562998521-1
  dizi-xnu-adt-parse-probe-40560506106-1
  dizi-public-uefi-40534403345-1
  dizi-public-uefi-40487237658-1
  dizi-public-uefi-40455830003-1
  dizi-public-uefi-40455314618-1
  dizi-public-uefi-40364858947-1
  dizi-public-uefi-40358544404-1
  dizi-public-uefi-40342440746-1
)
protected=(
  dizi-xnu-mmu-first-nosp-40700727875-1
  dizi-xnu-mmu-stackless-40700771901-1
  dizi-xnu-mmu-reg-stages-40649020254-1
  dizi-xnu-bootstrap-stages-40647473480-1
  dizi-xnu-ebs-no-kep-40641321399-1
  dizi-xnu-first-opcode-no-kep-40643799207-1
  dizi-public-uefi-40544976346-1
  dizi-xnu-source-40552223877
  dizi-xnu-prelinked-window-probe-40574804304-1
)
for tag in "${obsolete[@]}"; do
  for keep in "${protected[@]}"; do
    if [[ "$tag" == "$keep" ]]; then
      echo "FATAL: protected tag in obsolete list: $tag" >&2; exit 1
    fi
  done
done
echo "Protected control releases:"
printf '  KEEP %s\n' "${protected[@]}"
echo "Obsolete prerelease allowlist: ${#obsolete[@]}"
: > cleanup-dizi-old-releases.log
for tag in "${obsolete[@]}"; do
  if ! gh release view "$tag" --repo "$GITHUB_REPOSITORY" >/dev/null 2>&1; then
    echo "SKIP missing: $tag" | tee -a cleanup-dizi-old-releases.log
    continue
  fi
  is_pre="$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/${tag}" --jq '.prerelease')"
  if [[ "$is_pre" != true ]]; then
    echo "FATAL: refusing to delete non-prerelease $tag" >&2; exit 1
  fi
  # Keep git tags (no --cleanup-tag): commits and source history unaffected.
  gh release delete "$tag" --yes --repo "$GITHUB_REPOSITORY"
  echo "DELETED: $tag" | tee -a cleanup-dizi-old-releases.log
done
echo "Done. Only named old prereleases removed; 9 key releases protected."

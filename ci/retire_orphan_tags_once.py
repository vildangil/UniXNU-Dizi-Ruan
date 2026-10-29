#!/usr/bin/env python3
"""One-time, SHA-pinned cleanup of orphan *Git refs*, never GitHub Releases.

GitHub Actions main branch only; exclusively names in the archived markdown
manifest and only if no corresponding Release currently exists. Ref SHA is
checked immediately before every deletion. No branch, commit, release asset
or unrelated tag is modified.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = "vildangil/UniXNU-Dizi-Ruan"
ARCHIVE = Path("docs/TAG_RETIREMENT_2026-10-29.md")
CRITICAL = {"dizi-xnu-latest-test", "dizi-xnu-five-nosp-base"}
ROW = re.compile(r"^\| \`([a-z0-9][a-z0-9-]+)\` \| \`([0-9a-f]{40})\` \|$", re.M)
API = "https://api.github.com/repos/" + REPO


def call(method: str, url: str, token: str):
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dizi-tag-cleanup-once",
    }, method=method)
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as error:
        if error.code == 404:
            return 404, None
        raise RuntimeError(f"GitHub {method} {url.split('/repos/')[-1]}: HTTP {error.code}") from error


def releases(token: str) -> set[str]:
    out = set()
    for page in range(1, 20):
        status, data = call("GET", f"{API}/releases?per_page=100&page={page}", token)
        if status != 200 or not isinstance(data, list):
            raise ValueError("Release enumeration failed")
        out.update(x["tag_name"] for x in data)
        if len(data) < 100:
            return out
    raise ValueError("Release pagination exceeds safety bound")


def read_targets() -> list[tuple[str, str]]:
    if not ARCHIVE.is_file():
        raise ValueError("Missing pinned archive")
    rows = ROW.findall(ARCHIVE.read_text(encoding="utf-8"))
    if len(rows) != 23 or len(set(tag for tag, _ in rows)) != 23:
        raise ValueError("Manifest must contain exactly the 23 approved unique tags")
    if any(not tag.startswith(("dizi-xnu-", "dizi-public-uefi-")) for tag, _ in rows):
        raise ValueError("Unapproved tag name")
    if CRITICAL.intersection(tag for tag, _ in rows):
        raise ValueError("Critical release tag in deletion manifest")
    return rows


def current_ref(tag: str, token: str) -> str | None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]+", tag):
        raise ValueError("Invalid ref")
    code, ref = call("GET", f"{API}/git/ref/tags/{quote(tag, safe='')}", token)
    if code == 404:
        return None
    if code != 200 or ref.get("ref") != f"refs/tags/{tag}" or "sha" not in ref.get("object", {}):
        raise ValueError(f"Unexpected tag ref response for {tag}")
    return ref["object"]["sha"]


def run(execute: bool) -> None:
    if os.getenv("GITHUB_REPOSITORY") != REPO or os.getenv("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Cleanup is restricted to Dizi main branch")
    if os.getenv("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}:
        raise ValueError("Cleanup requires main push or owner manual dispatch")
    token = os.getenv("GH_TOKEN")
    if not token:
        raise ValueError("Missing short-lived GitHub Actions token")
    targets = read_targets()
    active_releases = releases(token)
    if not CRITICAL.issubset(active_releases):
        raise ValueError("Protected releases missing: refusing cleanup")
    if any(tag in active_releases for tag, _ in targets):
        raise ValueError("Target is attached to an existing Release")

    # Check *all* targets before deleting *any* refs.
    not_found = []
    for tag, expected in targets:
        sha = current_ref(tag, token)
        if sha is None:
            not_found.append(tag)
        elif sha != expected:
            raise ValueError(f"Tag changed since archive: {tag}, expected {expected}, found {sha}")
    print(f"Preflight: {len(targets)} intended orphan refs; {len(not_found)} already missing; "
          f"{len(active_releases)} protected Release tags.")
    if not execute:
        print("Dry-run completed; no refs deleted")
        return

    deleted = 0
    for tag, expected in targets:
        # Recheck releases and the exact ref object SHA just before mutation.
        if tag in releases(token):
            raise ValueError("Release appeared during cleanup: " + tag)
        sha = current_ref(tag, token)
        if sha is None:
            print("Already absent:", tag)
            continue
        if sha != expected:
            raise ValueError("Tag changed during cleanup: " + tag)
        code, _ = call("DELETE", f"{API}/git/refs/tags/{quote(tag, safe='')}", token)
        if code not in (200, 204):
            raise ValueError(f"DELETE response unexpected for {tag}: {code}")
        deleted += 1
        print("Deleted orphan tag ref:", tag)
    remaining = [(tag, current_ref(tag, token)) for tag, _ in targets]
    if any(sha is not None for _, sha in remaining):
        raise ValueError("Some historical tag refs still exist")
    after = releases(token)
    if not active_releases.issubset(after):
        raise ValueError("Release tag list changed unexpectedly; inspect immediately")
    for tag in active_releases:
        if current_ref(tag, token) is None:
            raise ValueError("Release tag ref missing after cleanup: " + tag)
    print(f"SUCCESS: removed {deleted} orphan refs. All {len(active_releases)} released tags intact.")
    with open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"), "a", encoding="utf-8") as f:
        f.write(f"Pruned **{deleted}** orphan Dizi Git tags; **{len(active_releases)}** release tags preserved. "
                f"Original commit SHA archive: \`{ARCHIVE}\`.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        run(args.execute)
    except (ValueError, RuntimeError, HTTPError) as exc:
        print("TAG CLEANUP ABORTED:", exc, file=sys.stderr)
        raise SystemExit(1)

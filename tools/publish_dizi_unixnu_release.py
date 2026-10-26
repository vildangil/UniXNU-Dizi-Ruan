#!/usr/bin/env python3
"""Publish an already built and verified DIZI self-hosted image to a GitHub pre-release.

No compilation, firmware flashing, Telegram secrets, host root or GitHub Actions
artifact storage. Assets on a PUBLIC repository are PUBLIC. This script refuses
to publish without matching SHA-256 metadata and an Android boot-v4 header.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = "vildangil/dizi_IpadOS_maybe"
BOOT = "Mu-dizi-PMIC-R3-UniXNU-NOT-FLASHABLE.img"
FD = "SILICIUM_UEFI-dizi-PMIC-R3-UniXNU.fd"
FAT = "DIZI-UNIXNU-FAT.img"
REQUIRED = (BOOT, FD, FAT, "SHA256SUMS.txt", "README-DO-NOT-FLASH.txt",
            "FD_BOOT_MATCH.json", "FV_SELECTOR_REPORT.json")
EXTRA = ("DIZI_SOURCE_SHA.txt", "UNIXNU_OVERLAY.json", "SELECTOR_OVERLAY.json",
         "DIZI_BUTTONS.json", "NATIVE_MENU_OVERLAY.json", "PMIC_UNIXNU_BRIDGE.json",
         "XNU_KERNEL_CANDIDATES.json", "UNIXNU_FV_VERIFICATION.json")
KNOWN_VERIFIED_BOOT_SHA256 = ""
API = "https://api.github.com"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(directory: Path, run_id: str, *, strict_known_sha: bool = False) -> list[Path]:
    if not re.fullmatch(r"[0-9]{8,16}", run_id):
        raise ValueError("run_id must be a numeric GitHub Actions run ID")
    directory = directory.resolve(strict=True)
    files = []
    for filename in REQUIRED:
        path = directory / filename
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise FileNotFoundError("Required verified output missing: " + filename)
        files.append(path)
    boot = directory / BOOT
    with boot.open("rb") as stream:
        header = stream.read(48)
    if len(header) < 44 or header[:8] != b"ANDROID!" or struct.unpack_from("<I", header, 40)[0] != 4:
        raise ValueError("Refusing to publish: not an Android boot-v4 image")

    expected = {}
    for line in (directory / "SHA256SUMS.txt").read_text().splitlines():
        match = re.fullmatch(r"([a-fA-F0-9]{64})  \*?([^/\\]+)", line)
        if not match:
            raise ValueError("Invalid SHA256SUMS.txt line")
        expected[match.group(2)] = match.group(1).lower()
    for name in (BOOT, FD, FAT):
        if expected.get(name) != digest(directory / name):
            raise ValueError("SHA256 mismatch (or missing entry): " + name)
    if strict_known_sha and digest(boot) != KNOWN_VERIFIED_BOOT_SHA256:
        raise ValueError("Archived boot image differs from the verified 40271537578 image")
    if "XNU FAT payload included: true" not in (directory / "README-DO-NOT-FLASH.txt").read_text():
        raise ValueError("Refusing to publish firmware-only or unknown-payload image")
    for name in ("FD_BOOT_MATCH.json", "FV_SELECTOR_REPORT.json"):
        json.loads((directory / name).read_text())

    for name in EXTRA:
        path = directory / name
        if path.is_file() and not path.is_symlink() and path.stat().st_size:
            files.append(path)
    return files


def request(method: str, endpoint: str, token: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data is not None else None
    req = Request(
        API + endpoint, data=body, method=method,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "DIZI-selfhost-delivery",
            **({"Content-Type": "application/json"} if body is not None else {}),
        },
    )
    try:
        with urlopen(req, timeout=60) as reply:
            return json.load(reply)
    except HTTPError as exc:
        # Never print API response bodies, which may contain sensitive URLs.
        raise RuntimeError("GitHub API " + method + " failed (HTTP " + str(exc.code) + ")") from None


def publish(directory: Path, run_id: str, sha: str, token: str, strict_known_sha: bool) -> str:
    if not token:
        raise ValueError("GITHUB_TOKEN missing")
    if not re.fullmatch("[0-9a-f]{40}", sha):
        raise ValueError("Invalid 40-character source commit SHA")
    paths = validate(directory, run_id, strict_known_sha=strict_known_sha)
    tag = "dizi-pmic-r3-unixnu-" + run_id
    endpoint = "/repos/" + REPO + "/releases/tags/" + quote(tag)
    try:
        release = request("GET", endpoint, token)
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
        release = request("POST", "/repos/" + REPO + "/releases", token, {
            "tag_name": tag,
            "target_commitish": sha,
            "name": "DIZI UniXNU / self-hosted experimental #" + run_id,
            "body": (
                "UNVERIFIED hardware experiment. NOT bootable iPadOS or a working "
                "Android/XNU dualboot. NEVER flash this image to any Android "
                "partition. Use only a previously validated reversible fastboot boot.\n\n"
                "Original successful self-hosted run: https://github.com/" + REPO
                + "/actions/runs/" + run_id + "\n"
                "Boot image SHA256: " + digest(directory / BOOT)
            ),
            "draft": False,
            "prerelease": True,
        })
    release_id = release["id"]
    done = {item["name"]: item for item in release.get("assets", [])}
    for path in paths:
        if path.name in done:
            asset = done[path.name]
            if asset.get("size") != path.stat().st_size:
                raise ValueError("Release asset name already exists with different size: " + path.name)
            print("Already uploaded:", path.name, flush=True)
            continue
        address = (
            "https://uploads.github.com/repos/" + REPO + "/releases/" + str(release_id)
            + "/assets?name=" + quote(path.name, safe="")
        )
        # curl streams large .img data instead of buffering hundreds of MiB
        # into a Python request. Token is passed by environment, not argv.
        script = (
            'exec curl --fail-with-body --silent --show-error --retry 3 '
            '--connect-timeout 30 --max-time 1800 '
            '-H "Authorization: Bearer $GITHUB_TOKEN" '
            '-H "Accept: application/vnd.github+json" '
            '-H "X-GitHub-Api-Version: 2022-11-28" '
            '-H "Content-Type: application/octet-stream" '
            '--data-binary "@$DIZI_ASSET_PATH" "$DIZI_UPLOAD_URL"'
        )
        env = {**os.environ, "GITHUB_TOKEN": token,
               "DIZI_ASSET_PATH": str(path), "DIZI_UPLOAD_URL": address}
        proc = subprocess.run(["sh", "-c", script], env=env, capture_output=True)
        if proc.returncode:
            # Never print token-bearing curl messages or upload response.
            raise RuntimeError("Release asset upload failed: " + path.name +
                               " (curl exit " + str(proc.returncode) + ")")
        try:
            uploaded = json.loads(proc.stdout)
        except (ValueError, UnicodeDecodeError):
            raise RuntimeError("Unexpected response after uploading " + path.name) from None
        if uploaded.get("state") != "uploaded" or uploaded.get("size") != path.stat().st_size:
            raise RuntimeError("Release asset not confirmed: " + path.name)
        print("Uploaded:", path.name, "bytes:", path.stat().st_size, flush=True)
    url = release["html_url"]
    print("Release:", url)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write("## DIZI UniXNU downloadable build\n\n")
            out.write("**Experimental — never flash to Android partitions.**\n\n")
            out.write("[Download the release](" + url + ")\n\n")
            out.write("Includes `boot.img`, matching EDK2 FD, FAT XNU payload, SHA256SUMS.\n")
    return url


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--directory", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--source-sha", required=True)
    ap.add_argument("--strict-known-sha", action="store_true")
    args = ap.parse_args()
    publish(args.directory, args.run_id, args.source_sha,
            os.environ.get("GITHUB_TOKEN", ""), args.strict_known_sha)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Exceptions here contain no auth header or request body.
        print("ERROR:", type(exc).__name__, str(exc), file=sys.stderr)
        sys.exit(1)

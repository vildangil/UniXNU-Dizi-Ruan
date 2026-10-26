#!/usr/bin/env python3
"""Stamp a pinned DIZI EDK2 selector with build/run identity before compilation.

No privileged operations; modifies only the selector source staged by the
existing overlay and writes an optional JSON manifest for reproducibility.
"""
import argparse
import json
import re
from pathlib import Path

PLACEHOLDER = '#define DIZI_BUILD_STAMP "R3-UNSTAMPED"'
STAGED = Path("Platforms/Xiaomi/DiziBootPkg/BootSelector/BootSelector.c")


def stamp(root: Path, run_id: str, source_sha: str, manifest: Path | None = None) -> str:
    if not re.fullmatch(r"[1-9][0-9]{0,18}", run_id):
        raise ValueError("invalid GitHub Actions run ID")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source SHA must be full 40-character lowercase hexadecimal")
    tag = f"R3-{run_id}-{source_sha[:8]}"
    path = root / STAGED
    content = path.read_text()
    if content.count(PLACEHOLDER) != 1:
        raise ValueError("selector is already stamped or the known source changed")
    path.write_text(content.replace(PLACEHOLDER,
                         f'#define DIZI_BUILD_STAMP "{tag}"'))
    result = {"build_tag": tag, "run_id": run_id, "source_sha": source_sha,
              "staged_file": str(STAGED), "hardware_verified": False}
    if manifest is not None:
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, indent=2) + "\n")
    return tag


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mu_checkout", type=Path)
    p.add_argument("--run-id", required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--manifest", type=Path)
    a = p.parse_args()
    print(stamp(a.mu_checkout, a.run_id, a.source_sha, a.manifest))


if __name__ == "__main__":
    main()

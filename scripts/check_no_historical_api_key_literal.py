#!/usr/bin/env python3
"""Detect the historical devtr6 API key literal without storing the literal."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path


HISTORICAL_DEVTR6_API_KEY_SHA256 = (
    "4e0a57d54be0f0736ef601de6ba2c0eef0b4216850f0ce1f9f1ef9b113a77ada"
)
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{20,}")


def candidate_files(repo_root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        repo_root / name.decode("utf-8")
        for name in result.stdout.split(b"\0")
        if name
    ]


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def find_matching_locations(
    repo_root: Path,
    target_sha256: str = HISTORICAL_DEVTR6_API_KEY_SHA256,
) -> list[str]:
    matches: list[str] = []

    for file_path in candidate_files(repo_root):
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        rel_path = file_path.relative_to(repo_root)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(
                token_digest(match.group(0)) == target_sha256
                for match in TOKEN_RE.finditer(line)
            ):
                matches.append(f"{rel_path}:{line_no}")
    return matches


def main(
    repo_root: Path | None = None,
    target_sha256: str = HISTORICAL_DEVTR6_API_KEY_SHA256,
) -> int:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]
    matches = find_matching_locations(repo_root, target_sha256)

    if matches:
        print(
            "historical devtr6 API key literal detected at:",
            file=sys.stderr,
        )
        for location in matches:
            print(location, file=sys.stderr)
        return 1

    print("historical devtr6 API key literal not found in indexed/untracked non-ignored files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

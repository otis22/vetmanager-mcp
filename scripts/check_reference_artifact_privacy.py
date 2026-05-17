#!/usr/bin/env python3
"""Detect Stage 164 reference-artifact privacy regressions without raw literals."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import NamedTuple


REFERENCE_ARTIFACTS = (
    Path("artifacts/vetmanager_openapi_v6.json"),
    Path("artifacts/vetmanager_postman_collection.json"),
    Path("artifacts/api_entity_reference-ru.md"),
    Path("artifacts/api-research-notes-ru.md"),
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HEX_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{16,}\b")

DENYLIST_SHA256 = {
    "61097a8108512dbb04c61cea2c5e2291b31dacc2404e882b2aa12688e587b088": "stage164-clinic-email-1",
    "700d29f135ef222c303bd2eb5c0b5846ef6b80ac381519b11cd1f37075d7d39c": "stage164-clinic-email-2",
    "87924606b4131a8aceeeae8868531fbb9712aaa07a5d3a756b26ce0f5d6ca674": "stage164-generic-email-1",
    "e6c6452a01b92a799548cf12a1ed5448fd0d3767fa070f32cd63e0885b399220": "stage164-generated-email-1",
    "ef88f0b5351d831bef3415e8069e0bf3cdbb0d8b6562f52b8368de4bec111cb1": "stage164-generated-email-2",
    "263f43a0541e5fc00787cb9675bfa403031330dd2bb62bd24d586af672e43521": "stage164-generated-email-3",
    "69770b5112db46a8a40b1cfe25295ca083c6a2686ce43ce3f193ce46a536ecf5": "stage164-passwd-hash-1",
}


class PrivacyViolation(NamedTuple):
    path: Path
    line_no: int
    label: str

    def format(self, repo_root: Path) -> str:
        return f"{self.path.relative_to(repo_root)}:{self.line_no} {self.label}"


class MissingReferenceArtifactError(FileNotFoundError):
    """Raised when a required Stage 164 reference artifact is absent."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_passwd_hash(value: str) -> str:
    return value.strip()


def scan_text(
    path: Path,
    text: str,
    denylist_sha256: dict[str, str] = DENYLIST_SHA256,
) -> list[PrivacyViolation]:
    violations: list[PrivacyViolation] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in EMAIL_RE.finditer(line):
            digest = sha256_text(normalize_email(match.group(0)))
            if digest in denylist_sha256:
                violations.append(PrivacyViolation(path, line_no, denylist_sha256[digest]))

        for match in HEX_TOKEN_RE.finditer(line):
            digest = sha256_text(normalize_passwd_hash(match.group(0)))
            if digest in denylist_sha256:
                violations.append(PrivacyViolation(path, line_no, denylist_sha256[digest]))
    return violations


def find_violations(
    repo_root: Path,
    artifacts: tuple[Path, ...] = REFERENCE_ARTIFACTS,
    denylist_sha256: dict[str, str] = DENYLIST_SHA256,
) -> list[PrivacyViolation]:
    violations: list[PrivacyViolation] = []
    for rel_path in artifacts:
        path = repo_root / rel_path
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise MissingReferenceArtifactError(str(rel_path)) from None
        violations.extend(scan_text(path, text, denylist_sha256))
    return violations


def main(repo_root: Path | None = None) -> int:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    try:
        violations = find_violations(repo_root)
    except MissingReferenceArtifactError as exc:
        print(f"required Stage 164 reference artifact is missing: {exc}", file=sys.stderr)
        return 1
    if violations:
        print("stage164 reference artifact privacy violations detected:", file=sys.stderr)
        for violation in violations:
            print(violation.format(repo_root), file=sys.stderr)
        return 1

    print("stage164 reference artifact privacy deny-list not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

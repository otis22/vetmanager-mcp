#!/usr/bin/env python3
"""Privacy checks for the Stage 165 security findings inventory."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.check_no_historical_api_key_literal as stage163
import scripts.check_reference_artifact_privacy as stage164


TARGET = Path("artifacts/security/stage-165-critical-findings-inventory.md")
ALLOWED_EMAIL_DOMAINS = {"example.com", "example.net", "example.org"}


def _assert_regex_self_tests() -> None:
    self_tests = (
        (
            r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b",
            "eyJabc.eyJdef123.sigxyz",
            0,
        ),
        (r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", "someone@gmail.com", 0),
        (r"\b[A-Za-z0-9]{32,}\b", "0123456789abcdef0123456789abcdef01234567", 0),
        (r"(?:\+7|8)[\s(.-]*\d{3}[\s). -]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}", "+7 999 123 45 67", 0),
        (r"\b(?:chat|tg|telegram)[ _-]?id\s*[:=]?\s*\d{6,}\b", "chat_id 1234567", re.I),
        (r"\b(?:ул\.|улица|проспект|пр-т|дом|квартира|address\s*:)\b", "улица Ленина", re.I),
        (
            r"(?i)\b(?:token|secret|api[_-]?key|bearer|password|pepper)\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_+/=-]{16,})",
            "api_key=abc_def-ghi+jkl/mno=pqr",
            0,
        ),
        (
            r"(?i)\b(?:token|secret|api[_-]?key|bearer|password|pepper)\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_+/=-]{16,})",
            '"api_key": "abc_def-ghi+jkl/mno=pqr"',
            0,
        ),
    )
    for pattern, sample, flags in self_tests:
        if not re.search(pattern, sample, flags):
            raise RuntimeError(f"Stage 165 privacy regex self-test failed: {pattern}")


def find_generic_privacy_problems(text: str) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []

    for match in re.finditer(r"\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b", text):
        problems.append(("jwt-like", match.group(0)))
    for match in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", text):
        if match.group(1).lower() not in ALLOWED_EMAIL_DOMAINS:
            problems.append(("email", match.group(0)))
    for match in re.finditer(r"(?:\+7|8)[\s(.-]*\d{3}[\s). -]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}", text):
        problems.append(("phone-like", match.group(0)))
    for match in re.finditer(r"\b(?:chat|tg|telegram)[ _-]?id\s*[:=]?\s*\d{6,}\b", text, re.I):
        problems.append(("chat-id-like", match.group(0)))
    for match in re.finditer(r"\b(?:ул\.|улица|проспект|пр-т|дом|квартира|address\s*:)\b", text, re.I):
        problems.append(("address-like", match.group(0)))
    for match in re.finditer(
        r"(?i)\b(?:token|secret|api[_-]?key|bearer|password|pepper)\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_+/=-]{16,})",
        text,
    ):
        value = match.group(1)
        if "redacted" not in value.lower() and "placeholder" not in value.lower():
            problems.append(("secret-assignment-like", match.group(0)))
    for match in re.finditer(r"\b[A-Za-z0-9]{32,}\b", text):
        token = match.group(0)
        prefix = text[max(0, match.start() - 8) : match.start()]
        if re.fullmatch(r"[0-9a-f]{40}", token) and prefix.endswith("commit:"):
            continue
        if re.fullmatch(r"[0-9a-f]{64}", token) and prefix.endswith("sha256:"):
            continue
        problems.append(("long-token", token[:12] + "..."))

    return problems


def main() -> int:
    _assert_regex_self_tests()
    if not TARGET.exists():
        print(f"{TARGET} does not exist", file=sys.stderr)
        return 1

    text = TARGET.read_text(encoding="utf-8")

    stage163_hits = stage163.find_matching_locations(REPO_ROOT, stage163.HISTORICAL_DEVTR6_API_KEY_SHA256)
    stage164_hits = stage164.scan_text(TARGET.resolve(), text)
    if any("stage-165-critical-findings-inventory.md" in hit for hit in stage163_hits) or stage164_hits:
        print("Stage 165 inventory contains sanitized-deny-list material", file=sys.stderr)
        return 1

    generic = find_generic_privacy_problems(text)
    if generic:
        print(f"Potential privacy token(s) in inventory: {generic}", file=sys.stderr)
        return 1

    print("stage165 inventory privacy check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

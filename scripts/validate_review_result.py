#!/usr/bin/env python3
"""Validate a Claude structured-review envelope and print its verdict."""

from __future__ import annotations

import json
import sys
from typing import Any


def _invalid(message: str) -> int:
    print(f"review gate: {message}", file=sys.stderr)
    return 2


def _is_finding(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"severity", "file", "line", "reason"}
        and isinstance(value["severity"], str)
        and isinstance(value["file"], str)
        and isinstance(value["line"], (int, float))
        and not isinstance(value["line"], bool)
        and isinstance(value["reason"], str)
    )


def validate_envelope(envelope: Any) -> dict[str, Any]:
    if not isinstance(envelope, dict) or envelope.get("is_error") is not False:
        raise ValueError("invalid Claude envelope")
    result = envelope.get("result")
    if not isinstance(result, str) or not result:
        raise ValueError("empty Claude result")
    try:
        review = json.loads(result)
    except json.JSONDecodeError as exc:
        raise ValueError("Claude result is not JSON") from exc
    if not isinstance(review, dict) or not isinstance(review.get("findings"), list):
        raise ValueError("review result does not match findings schema")
    if not all(_is_finding(finding) for finding in review["findings"]):
        raise ValueError("review result does not match findings schema")
    if set(review) != {"findings"}:
        raise ValueError("review result does not match findings schema")
    return review


def main() -> int:
    try:
        envelope = json.load(sys.stdin)
    except json.JSONDecodeError:
        return _invalid("Claude envelope is not JSON")
    try:
        review = validate_envelope(envelope)
    except ValueError as exc:
        return _invalid(str(exc))
    json.dump(review, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

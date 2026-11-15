#!/usr/bin/env python3
"""Run one offline pytest owner with addressable resource diagnostics."""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from warning_policy import build_warning_error_flags

_FORBIDDEN_MARKERS = {"real_api", "real_browser", "postgres"}
_CREDENTIAL_ENV = {"TEST_API_KEY", "TEST_USER_TOKEN", "TEST_USER_LOGIN", "TEST_USER_PASSWORD"}
_SECRET_NAME = re.compile(r"(?:KEY|TOKEN|PASSWORD|SECRET|CREDENTIAL|AUTH)", re.I)
_URL = re.compile(r"(?:https?|postgresql(?:\+asyncpg)?|redis)://[^\s\"'<>]+", re.I)
_BEARER_HEADER = re.compile(r"\bauthorization\s*[:=]\s*Bearer\s+[^\s,;]+", re.I)
_SECRET_ASSIGNMENT = re.compile(r"\b(?:authorization|api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+", re.I)


def redact_output(value: str) -> str:
    """Remove configured secret values and common credential/URL shapes."""
    for name, secret in os.environ.items():
        if _SECRET_NAME.search(name) and len(secret) >= 4:
            value = value.replace(secret, "[REDACTED]")
    value = _URL.sub("[REDACTED_URL]", value)
    value = _BEARER_HEADER.sub("[REDACTED_CREDENTIAL]", value)
    return _SECRET_ASSIGNMENT.sub("[REDACTED_CREDENTIAL]", value)


def build_command(target: str, evidence_dir: Path) -> list[str]:
    """Reject broad/external targets before building one strict pytest call."""
    path = Path(target.split("::", 1)[0])
    if not target.startswith("tests/test_") or path.suffix != ".py" or not path.is_file():
        raise ValueError("diagnostic requires a single owning file or node")
    resolved = path.resolve()
    if resolved.parent != ROOT / "tests":
        raise ValueError("diagnostic requires a single owning file or node")
    tree = ast.parse(resolved.read_text(encoding="utf-8"))
    if any(isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_MARKERS for node in ast.walk(tree)):
        raise ValueError("diagnostic accepts offline nodes only")
    outside = evidence_dir.resolve()
    if outside == ROOT or ROOT in outside.parents:
        raise ValueError("diagnostic evidence must be outside the repository")
    if any(os.environ.get(name) for name in _CREDENTIAL_ENV):
        raise ValueError("diagnostic requires an environment without test credentials")
    return [
        sys.executable,
        *[item for flag in build_warning_error_flags() for item in ("-W", flag)],
        "-m", "pytest", target, "-vv", "-s", "--log-cli-level=DEBUG",
    ]


def run(target: str, evidence_dir: Path) -> int:
    """Run the exact requested scope and propagate pytest's exit status."""
    command = build_command(target, evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if evidence_dir.stat().st_mode & 0o077:
        raise ValueError("diagnostic evidence directory must be private")
    env = {**os.environ, "PYTHONTRACEMALLOC": "5", "REAL_JUNIT_DIR": str(evidence_dir)}
    result = subprocess.run(command, env=env, check=False, capture_output=True, text=True)
    for name, content in (("stdout.txt", result.stdout), ("stderr.txt", result.stderr)):
        fd = os.open(evidence_dir / name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(redact_output(content))
    return result.returncode


def main() -> int:
    """Parse the CLI without accepting a directory or wildcard scope."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="one tests/test_*.py file or ::node")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args.target, args.evidence_dir)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())

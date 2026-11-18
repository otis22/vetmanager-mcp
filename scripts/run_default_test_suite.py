#!/usr/bin/env python3
"""Run the default test contour with blocking warnings promoted to errors."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from test_contours import DEFAULT_TEST_CONTOUR
from warning_policy import DEFAULT_SUITE_WARNING_POLICY, build_warning_error_flags
from scripts.offline_gate_manifest import check_gate, check_inventory, source_fingerprint


def main() -> int:
    if DEFAULT_SUITE_WARNING_POLICY.warnings_allowed != 0:
        raise SystemExit("Default suite warning policy must require zero warnings.")

    try:
        check_inventory("default")
    except ValueError as exc:
        print(f"Default inventory preflight rejected: {exc}", file=sys.stderr)
        return 1

    gate = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "check_known_issue_tool_names.py")],
        env=dict(os.environ),
        check=False,
    )
    if gate.returncode != 0:
        return gate.returncode

    junit = Path(os.environ.get("DEFAULT_JUNIT_XML", "/tmp/stage465-default.xml"))
    command = [
        sys.executable,
        *[item for flag in build_warning_error_flags() for item in ("-W", flag)],
        "-m",
        "pytest",
        "tests/",
        "-v",
        "--cov",
        "--cov-config=.coveragerc",
        "--cov-report=term-missing:skip-covered",
        "--cov-report=xml:coverage.xml",
        f"--junitxml={junit}",
        "-m",
        DEFAULT_TEST_CONTOUR.marker_expression,
    ]
    env = dict(os.environ)
    starting_fingerprint = source_fingerprint()
    completed = subprocess.run(command, env=env, check=False)
    if completed.returncode:
        return completed.returncode
    try:
        check_gate(
            "default", junit,
            PROJECT_ROOT / ".stage465-default-gate.json",
            starting_fingerprint,
        )
    except ValueError as exc:
        print(f"Default manifest gate rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

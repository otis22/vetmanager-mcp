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


def main() -> int:
    if DEFAULT_SUITE_WARNING_POLICY.warnings_allowed != 0:
        raise SystemExit("Default suite warning policy must require zero warnings.")

    command = [
        sys.executable,
        *[item for flag in build_warning_error_flags() for item in ("-W", flag)],
        "-m",
        "pytest",
        "tests/",
        "-v",
        "-m",
        DEFAULT_TEST_CONTOUR.marker_expression,
        "--cov=.",
        "--cov-report=term-missing:skip-covered",
        "--cov-fail-under=50",
    ]
    env = dict(os.environ)
    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

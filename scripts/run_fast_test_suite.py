#!/usr/bin/env python3
"""Run the fast inner-loop contour with blocking warnings as errors."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from test_contours import FAST_TEST_CONTOUR
from warning_policy import build_warning_error_flags


def main() -> int:
    command = [
        sys.executable,
        *[item for flag in build_warning_error_flags() for item in ("-W", flag)],
        "-m",
        "pytest",
        "tests/",
        "-v",
        "-m",
        FAST_TEST_CONTOUR.marker_expression,
    ]
    env = dict(os.environ)
    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

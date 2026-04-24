#!/usr/bin/env python3
"""Run the opt-in real contour with blocking warnings as errors."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from test_contours import OPT_IN_REAL_TEST_CONTOUR
from warning_policy import build_warning_error_flags


def main() -> int:
    warning_flags = [item for flag in build_warning_error_flags() for item in ("-W", flag)]
    base_command = [
        sys.executable,
        *warning_flags,
        "-m",
        "pytest",
        "-v",
        "-m",
        OPT_IN_REAL_TEST_CONTOUR.marker_expression,
    ]
    env = dict(os.environ)
    env.setdefault("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS", "0.5")
    commands = [
        [
            *base_command,
            "tests/",
            "-k",
            "not test_real_web_account_can_issue_bearer_and_call_tool",
        ],
        [
            *base_command,
            "tests/test_e2e_real.py::test_real_web_account_can_issue_bearer_and_call_tool",
        ],
    ]
    for command in commands:
        completed = subprocess.run(command, env=env, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

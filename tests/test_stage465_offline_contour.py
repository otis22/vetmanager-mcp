"""Stage 465 guards for the measured offline integration boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

from test_contours import DEFAULT_TEST_CONTOUR, FAST_TEST_CONTOUR


def test_fast_excludes_offline_while_default_keeps_it() -> None:
    assert "not offline_integration" in FAST_TEST_CONTOUR.marker_expression
    assert "not offline_integration" not in DEFAULT_TEST_CONTOUR.marker_expression


def test_measured_expensive_owner_is_marked_but_light_owner_is_not() -> None:
    command = [
        sys.executable, "-m", "pytest", "--collect-only", "-q", "-m",
        "offline_integration", "tests/test_web_auth.py",
        "tests/test_stage265_denial_reaches_the_agent.py",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "tests/test_web_auth.py::" in result.stdout
    assert "tests/test_stage265_denial_reaches_the_agent.py::" not in result.stdout


def test_fast_ci_rejects_wall_time_above_180_seconds() -> None:
    workflow = yaml.safe_load(Path(".github/workflows/test.yml").read_text())
    step = next(step for step in workflow["jobs"]["fast"]["steps"]
                if step.get("name") == "Run fast contour")
    assert "elapsed=$(( SECONDS - started ))" in step["run"]
    assert "if (( elapsed > 180 )); then" in step["run"]
    assert "exit 1" in step["run"]

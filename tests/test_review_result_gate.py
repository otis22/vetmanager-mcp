"""Acceptance tests for the external structured-review gate."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path("scripts/validate_review_result.py")


def _envelope(result) -> str:
    return json.dumps({"is_error": False, "result": json.dumps(result)})


@pytest.mark.parametrize(
    ("review", "expected_code"),
    [
        (
            {"findings": [{"severity": "medium", "file": "tools/x.py", "line": 1, "reason": "reason"}]},
            0,
        ),
        ({"findings": []}, 0),
        ({"findings": [{"severity": "medium", "file": "tools/x.py", "line": 1}]}, 2),
        ({"findings": [{"severity": "medium", "file": "tools/x.py", "line": 1.5, "reason": "reason"}]}, 2),
        ({"findings": "not an array"}, 2),
        ([], 2),
    ],
)
def test_review_result_gate_acceptance_cases(review, expected_code) -> None:
    completed = subprocess.run(
        [str(SCRIPT)], input=_envelope(review), text=True, capture_output=True,
    )

    assert completed.returncode == expected_code
    if expected_code == 0:
        assert json.loads(completed.stdout) == review


def test_review_result_gate_documented_command_is_executable() -> None:
    completed = subprocess.run(
        [str(SCRIPT)], input=_envelope({"findings": []}), text=True, capture_output=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"findings": []}

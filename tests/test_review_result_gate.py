"""Acceptance tests for the external structured-review gate."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

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
        ({"findings": "not an array"}, 2),
        ([], 2),
    ],
)
def test_review_result_gate_acceptance_cases(review, expected_code) -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT)], input=_envelope(review), text=True, capture_output=True,
    )

    assert completed.returncode == expected_code
    if expected_code == 0:
        assert json.loads(completed.stdout) == review

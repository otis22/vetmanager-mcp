"""Stage 265.3: dead imports and locals fail the suite, not somebody's attention.

An orphaned constant survived a whole stage until it was spotted by hand during
review. The linter runs from here so it lives in CI without a separate job.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed in this image")
def test_repository_has_no_dead_imports_or_locals():
    result = subprocess.run(
        ["ruff", "check", "--no-cache", "--output-format", "concise", "."],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"dead code found:\n{result.stdout}{result.stderr}"


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed in this image")
def test_the_linter_would_notice_a_dead_import(tmp_path):
    """A linter nobody has seen fail is a linter nobody can trust."""
    specimen = tmp_path / "specimen.py"
    specimen.write_text("import json\n\n\ndef work():\n    return 1\n", encoding="utf-8")

    result = subprocess.run(
        ["ruff", "check", "--no-cache", "--output-format", "concise",
         "--select", "F401,F841", str(specimen)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "F401" in result.stdout

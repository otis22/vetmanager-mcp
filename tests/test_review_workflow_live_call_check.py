"""review_workflow_check.sh: write-path tools require a recorded live call.

CLAUDE.md 6.1. Two write tools shipped 100%-broken on 2026-08-23 with green
tests, because their mocks described a response shape Vetmanager never returns.
The check fires when a stage touches crud_update/crud_create and its own
AssumptionLog section records no live call.

The test image carries no git, so the script is driven with a stub `git` that
answers the two forms this check relies on.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "review_workflow_check.sh"

_WRITE_PATH_DIFF = """diff --git a/tools/sample.py b/tools/sample.py
--- a/tools/sample.py
+++ b/tools/sample.py
@@ -1 +1,4 @@
 BASELINE = 1
+
+async def update():
+    return await crud_update('/rest/api/x', 1, {})
"""

_READ_ONLY_DIFF = """diff --git a/tools/sample.py b/tools/sample.py
--- a/tools/sample.py
+++ b/tools/sample.py
@@ -1 +1 @@
-BASELINE = 1
+BASELINE = 2
"""


def _stub_git(bin_dir: Path, diff_text: str) -> None:
    """Answer `git diff [--cached] [--stat] -- tools/`; stay silent otherwise."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "git"
    script.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *--stat*) echo " 1 file changed, 3 insertions(+)" ;;\n'
        '  diff*) cat "$0.diff" ;;\n'
        "  *) : ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    (bin_dir / "git.diff").write_text(diff_text, encoding="utf-8")


def _repo(tmp_path: Path, *, assumption_body: str, diff_text: str = _WRITE_PATH_DIFF) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "PRD").mkdir()
    shutil.copy(SCRIPT, repo / "scripts" / SCRIPT.name)
    (repo / "Roadmap.md").write_text("## Этап 900. Проба — `in_progress`\n", encoding="utf-8")
    (repo / "PRD" / "этап-900-проба.md").write_text("## Цель\nпроба\n", encoding="utf-8")
    (repo / "AssumptionLog.md").write_text(assumption_body, encoding="utf-8")
    _stub_git(tmp_path / "bin", diff_text)
    return repo


def _run(repo: Path, tmp_path: Path) -> str:
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    result = subprocess.run(
        ["bash", "scripts/review_workflow_check.sh", "900"],
        cwd=repo, capture_output=True, text=True, check=False, env=env,
    )
    return result.stdout


@pytest.mark.parametrize("evidence", ["живым вызовом", "devtr6", "opt_in_real", "live call"])
def test_recorded_live_call_satisfies_the_check(tmp_path: Path, evidence: str) -> None:
    repo = _repo(tmp_path, assumption_body=f"## Этап 900. Проба\n\n- Проверено {evidence}: 201.\n")
    assert "missing_live_call" not in _run(repo, tmp_path)


def test_missing_live_call_is_reported(tmp_path: Path) -> None:
    repo = _repo(tmp_path, assumption_body="## Этап 900. Проба\n\n- Ничего про проверку не сказано.\n")
    assert "missing_live_call" in _run(repo, tmp_path)


def test_evidence_from_another_stage_does_not_count(tmp_path: Path) -> None:
    """The section boundary matters: a neighbour's live call is not ours."""
    repo = _repo(tmp_path, assumption_body=(
        "## Этап 900. Проба\n\n- Ничего про проверку не сказано.\n\n"
        "## Этап 901. Соседний\n\n- Проверено живым вызовом на devtr6: 201.\n"
    ))
    assert "missing_live_call" in _run(repo, tmp_path)


def test_check_stays_quiet_without_write_path_changes(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        assumption_body="## Этап 900. Проба\n\n- Ничего про проверку.\n",
        diff_text=_READ_ONLY_DIFF,
    )
    assert "missing_live_call" not in _run(repo, tmp_path)

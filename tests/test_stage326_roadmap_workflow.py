"""Этап 326: архив является частью завершения, а не невидимой историей."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FINDER = ROOT / "scripts" / "find_roadmap_stage.py"


def _run_finder(tmp_path: Path, queue: str, archive: str, stage: str = "237"):
    queue_path = tmp_path / "Roadmap.md"
    archive_path = tmp_path / "Roadmap-archive.md"
    queue_path.write_text(queue, encoding="utf-8")
    archive_path.write_text(archive, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(FINDER), stage, str(queue_path), str(archive_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def test_archived_stage_237_is_found_exactly_once() -> None:
    result = subprocess.run(
        [sys.executable, str(FINDER), "237"], cwd=ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("## Этап 237.")


def test_stage_lookup_rejects_missing_and_duplicate_headers(tmp_path: Path) -> None:
    missing = _run_finder(tmp_path, "## Этап 1. Один — `todo`\n", "# Архив\n")
    duplicate = _run_finder(
        tmp_path,
        "## Этап 237. Очередь — `done`\n",
        "## Этап 237. Архив — `done`\n",
    )
    assert missing.returncode == 1 and "найдено 0" in missing.stderr
    assert duplicate.returncode == 1 and "найдено 2" in duplicate.stderr


def test_completion_checker_accepts_the_archived_stage_237() -> None:
    result = subprocess.run(
        ["bash", "scripts/check_stage_completion.sh", "237"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "missing_roadmap_header" not in result.stdout


def test_workflow_checker_accepts_supervisor_pending(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    checker = scripts / "review_workflow_check.sh"
    checker.write_bytes((ROOT / "scripts/review_workflow_check.sh").read_bytes())
    (scripts / "find_roadmap_stage.py").write_bytes(FINDER.read_bytes())
    (tmp_path / "Roadmap.md").write_text(
        "## Этап 900. Решение владельца — `supervisor_pending`\n\n"
        "- 900.1 Ждёт решения. — `supervisor_pending`\n",
        encoding="utf-8",
    )
    (tmp_path / "Roadmap-archive.md").write_text("# Архив\n", encoding="utf-8")
    (tmp_path / "AssumptionLog.md").write_text("## Этап 900. Evidence\n", encoding="utf-8")
    prd = tmp_path / "PRD"
    prd.mkdir()
    (prd / "этап-900-test.md").write_text("## Цель\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(checker), "900"], cwd=tmp_path, text=True, capture_output=True
    )
    assert "roadmap_status_missing" not in result.stdout


def test_core_loop_orders_archive_before_structure_and_commit() -> None:
    for path in (ROOT / "CLAUDE.md", ROOT / ".cursor/rules/agent-workflow.mdc"):
        text = path.read_text(encoding="utf-8")
        archive = text.index("python3 scripts/archive_roadmap.py")
        structure = text.index("python3 scripts/check_roadmap_structure.py", archive)
        commit = text.index("Commit", structure)
        assert archive < structure < commit, path
    cursor = (ROOT / ".cursor/rules/agent-workflow.mdc").read_text(encoding="utf-8")
    assert "`Roadmap-archive.md`" in cursor
    assert "`supervisor_pending`" in (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

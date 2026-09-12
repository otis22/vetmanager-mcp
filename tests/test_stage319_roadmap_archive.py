"""Этап 319: очередь и архив проверяются исполнимыми правилами, не вниманием."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ARCHIVER = ROOT / "scripts" / "archive_roadmap.py"
CHECKER = ROOT / "scripts" / "check_roadmap_structure.py"


def _stage(number: str, status: str, body: str = "Текст.") -> str:
    if status in {"todo", "in_progress", "supervisor_pending"} and body == "Текст.":
        body = f"{body}\n\n- {number}.1 Открытая работа. — `{status}`"
    return f"## Этап {number}. Этап {number} — `{status}`\n\n{body}\n"


def _files(tmp_path: Path, roadmap: str, archive: str = "# Архив Roadmap\n\n") -> tuple[Path, Path]:
    queue, history = tmp_path / "Roadmap.md", tmp_path / "Roadmap-archive.md"
    queue.write_text(roadmap, encoding="utf-8")
    history.write_text(archive, encoding="utf-8")
    return queue, history


def _run_archiver(queue: Path, archive: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ARCHIVER), "--roadmap", str(queue), "--archive", str(archive)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def _run_gate(queue: Path, archive: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), str(queue), str(archive)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


def test_archive_moves_closed_stages_verbatim_and_second_run_is_a_noop(tmp_path: Path) -> None:
    queue, archive = _files(
        tmp_path,
        _stage("1", "done", "Дословный\nтекст.")
        + _stage("10", "stop")
        + _stage("11", "todo")
        + _stage("31", "in_progress"),
    )

    first = _run_archiver(queue, archive)
    assert first.returncode == 0, first.stderr
    assert "## Этап 1. Этап 1 — `done`\n\nДословный\nтекст.\n" in archive.read_text(encoding="utf-8")
    assert "## Этап 1." not in queue.read_text(encoding="utf-8")
    before = (queue.read_bytes(), archive.read_bytes())

    second = _run_archiver(queue, archive)
    assert second.returncode == 0, second.stderr
    assert (queue.read_bytes(), archive.read_bytes()) == before


def test_archive_appends_a_late_old_closure_and_gate_stays_green(tmp_path: Path) -> None:
    queue, archive = _files(
        tmp_path,
        _stage("2", "done") + _stage("31", "in_progress"),
        "# Архив Roadmap\n\n" + _stage("5", "done"),
    )
    result = _run_archiver(queue, archive)
    assert result.returncode == 0, result.stderr
    assert archive.read_text(encoding="utf-8").endswith(_stage("2", "done"))
    assert _run_gate(queue, archive).returncode == 0


@pytest.mark.parametrize(
    ("queue", "archive", "message"),
    [
        (_stage("1", "done") + _stage("31", "todo"), "# Архив Roadmap\n", "закрытый этап 1 вне окна"),
        (_stage("31", "todo"), "# Архив Roadmap\n\n" + _stage("1", "todo"), "открытый этап 1 в архиве"),
        (_stage("1", "done") + _stage("31", "todo"), "# Архив Roadmap\n\n" + _stage("1", "done"), "этап 1 встречается"),
    ],
)
def test_distribution_gate_refuses_each_stage319_rule(
    tmp_path: Path, queue: str, archive: str, message: str
) -> None:
    roadmap, history = _files(tmp_path, queue, archive)

    result = _run_gate(roadmap, history)

    assert result.returncode == 1
    assert message in result.stdout


def test_repository_queue_and_archive_pass_the_distribution_gate() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER)], cwd=ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stdout

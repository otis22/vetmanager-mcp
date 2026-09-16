"""Этап 319: очередь и архив проверяются исполнимыми правилами, не вниманием."""

from __future__ import annotations

import importlib.util
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


def test_a_new_archive_uses_the_committed_header_byte_for_byte(tmp_path: Path) -> None:
    queue, archive = _files(tmp_path, _stage("1", "done") + _stage("31", "todo"))
    archive.unlink()

    result = _run_archiver(queue, archive)

    assert result.returncode == 0, result.stderr
    expected = (ROOT / "Roadmap-archive.md").read_text(encoding="utf-8").split("## Этап ", 1)[0]
    assert archive.read_text(encoding="utf-8").startswith(expected)


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


def test_exact_twenty_number_window_moves_max_minus_twenty_only(tmp_path: Path) -> None:
    queue, archive = _files(
        tmp_path,
        _stage("11", "done") + _stage("12", "done") + _stage("31", "todo"),
    )

    result = _run_archiver(queue, archive)

    assert result.returncode == 0, result.stderr
    assert "## Этап 11." in archive.read_text(encoding="utf-8")
    assert "## Этап 12." in queue.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("queue_text", "archive_text"),
    [
        (_stage("1", "done") + _stage("1", "todo") + _stage("31", "todo"), "# Архив\n"),
        (_stage("31", "todo"), "# Архив\n" + _stage("1", "done") + _stage("1", "stop")),
        (_stage("1", "done") + _stage("31", "todo"), "# Архив\n" + _stage("1", "done")),
    ],
)
def test_archive_rejects_duplicate_identity_without_changing_either_file(
    tmp_path: Path, queue_text: str, archive_text: str
) -> None:
    queue, archive = _files(tmp_path, queue_text, archive_text)
    before = queue.read_bytes(), archive.read_bytes()

    result = _run_archiver(queue, archive)

    assert result.returncode == 1
    assert "этап 1 встречается" in result.stderr
    assert (queue.read_bytes(), archive.read_bytes()) == before


def test_suffix_is_part_of_identity_not_a_duplicate(tmp_path: Path) -> None:
    queue, archive = _files(
        tmp_path,
        _stage("103", "done") + _stage("103a", "done") + _stage("131", "todo"),
    )

    result = _run_archiver(queue, archive)

    assert result.returncode == 0, result.stderr
    assert "## Этап 103." in archive.read_text(encoding="utf-8")
    assert "## Этап 103a." in archive.read_text(encoding="utf-8")


def _archive_module():
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("stage326_archive_roadmap", ARCHIVER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("failed_target", ["archive", "queue"])
def test_atomic_replacement_failure_keeps_both_targets_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_target: str
) -> None:
    queue, archive = _files(tmp_path, _stage("1", "done") + _stage("31", "todo"))
    before = queue.read_bytes(), archive.read_bytes()
    module = _archive_module()
    real_replace = module.os.replace
    failed = False

    def injected_replace(source, target):
        nonlocal failed
        if Path(target) == (archive if failed_target == "archive" else queue) and not failed:
            failed = True
            raise OSError("injected replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", injected_replace)
    result = module.main(["--roadmap", str(queue), "--archive", str(archive)])

    assert result == 1
    assert (queue.read_bytes(), archive.read_bytes()) == before


def test_atomic_replacement_commits_archive_before_queue(tmp_path: Path, monkeypatch) -> None:
    queue, archive = _files(tmp_path, _stage("1", "done") + _stage("31", "todo"))
    module = _archive_module()
    real_replace = module.os.replace
    targets: list[Path] = []

    def recording_replace(source, target):
        targets.append(Path(target))
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", recording_replace)
    assert module.main(["--roadmap", str(queue), "--archive", str(archive)]) == 0
    assert targets[:2] == [archive, queue]


def test_failed_rollback_preserves_recovery_copy(tmp_path: Path, monkeypatch) -> None:
    queue, archive = _files(tmp_path, _stage("1", "done") + _stage("31", "todo"))
    old_archive = archive.read_bytes()
    module = _archive_module()
    real_replace = module.os.replace
    calls = 0

    def injected_replace(source, target):
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError(f"injected replace failure {calls}")
        return real_replace(source, target)

    monkeypatch.setattr(module.os, "replace", injected_replace)
    result = module.main(["--roadmap", str(queue), "--archive", str(archive)])
    recovery_files = list(tmp_path.glob(f".{archive.name}.*"))

    assert result == 1
    assert recovery_files
    assert old_archive in [path.read_bytes() for path in recovery_files]


def test_prepare_failure_cleans_already_created_tempfiles(tmp_path: Path, monkeypatch) -> None:
    queue, archive = _files(tmp_path, _stage("1", "done") + _stage("31", "todo"))
    module = _archive_module()
    real_prepare = module._prepare
    calls = 0

    def injected_prepare(path, text):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected prepare failure")
        return real_prepare(path, text)

    monkeypatch.setattr(module, "_prepare", injected_prepare)
    result = module.main(["--roadmap", str(queue), "--archive", str(archive)])

    assert result == 1
    assert not list(tmp_path.glob(".Roadmap*"))


@pytest.mark.parametrize(
    ("queue", "archive", "message"),
    [
        (_stage("11", "done") + _stage("31", "todo"), "# Архив Roadmap\n", "закрытый этап 11 вне окна"),
        (_stage("31", "todo"), "# Архив Roadmap\n\n" + _stage("1", "todo"), "открытый этап 1 в архиве"),
        (_stage("1", "done") + _stage("31", "todo"), "# Архив Roadmap\n\n" + _stage("1", "done"), "этап 1 встречается"),
        (_stage("31", "todo"), "# Архив Roadmap\n\n" + _stage("12", "done"), "закрытый этап 12 из текущего окна"),
        (_stage("31", "todo"), "# Архив Roadmap\n\n" + _stage("40", "done"), "закрытый этап 40 из текущего окна"),
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


def test_distribution_maximum_is_computed_from_queue_and_archive(tmp_path: Path) -> None:
    queue, archive = _files(
        tmp_path,
        _stage("20", "done") + _stage("31", "todo"),
        "# Архив\n" + _stage("40", "done"),
    )
    result = _run_gate(queue, archive)
    assert result.returncode == 1
    assert "закрытый этап 20 вне окна" in result.stdout

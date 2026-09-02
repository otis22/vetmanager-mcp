"""Stage 279: the work queue is checked by a gate, not by attention.

Roadmap.md is past five thousand lines. On 2026-09-02 a review found two `todo`
items and one `supervisor_pending` item sitting inside `done` stages, a
duplicated item filed under a foreign stage number, and an open stage with no
items at all — none of them hidden, all of them past the point where reading
stops. The checker runs from here so it lives in CI without a separate job.

Every specimen below is a file the gate must reject. A gate nobody has seen
fail is a gate nobody can trust (CLAUDE.md 4.0).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHECKER = _REPO_ROOT / "scripts" / "check_roadmap_structure.py"
_ROADMAP = _REPO_ROOT / "Roadmap.md"


def _run(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CHECKER), str(path)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _specimen(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "Roadmap.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_the_repository_roadmap_is_well_formed():
    result = _run(_ROADMAP)
    assert result.returncode == 0, f"структура Roadmap.md нарушена:\n{result.stdout}"


def test_a_well_formed_specimen_passes(tmp_path):
    """The gate has to be able to say yes, or it says nothing."""
    result = _run(
        _specimen(
            tmp_path,
            "## Этап 1. Первый — `done`\n\n- 1.1 Сделано. — `done`\n\n"
            "## Этап 2. Второй — `todo`\n\n- 2.1 Не сделано. — `todo`\n",
        )
    )
    assert result.returncode == 0, result.stdout


def test_a_stage_heading_without_a_status_is_refused(tmp_path):
    result = _run(_specimen(tmp_path, "## Этап 1. Первый\n\n- 1.1 Сделано. — `done`\n"))
    assert result.returncode == 1
    assert "этап 1 без статуса" in result.stdout


def test_an_item_without_a_status_is_refused(tmp_path):
    result = _run(_specimen(tmp_path, "## Этап 1. Первый — `done`\n\n- 1.1 Сделано.\n"))
    assert result.returncode == 1
    assert "пункт 1.1 без статуса" in result.stdout


def test_an_item_filed_under_a_foreign_stage_is_refused(tmp_path):
    """The duplicate 97.7 lived under stage 104 for four months."""
    result = _run(
        _specimen(tmp_path, "## Этап 104. Гейты — `done`\n\n- 97.7 Чужой пункт. — `done`\n")
    )
    assert result.returncode == 1
    assert "пункт 97.7 стоит под этапом 104" in result.stdout


@pytest.mark.parametrize("item_status", ["todo", "in_progress", "supervisor_pending"])
@pytest.mark.parametrize("stage_status", ["done", "stop"])
def test_unfinished_work_under_a_closed_heading_is_refused(tmp_path, stage_status, item_status):
    result = _run(
        _specimen(
            tmp_path,
            f"## Этап 249. Закрытый — `{stage_status}`\n\n"
            f"- 249.1 Сделано. — `done`\n"
            f"- 249.3 Осталось. — `{item_status}`\n",
        )
    )
    assert result.returncode == 1
    assert f"пункт 249.3 остался `{item_status}`" in result.stdout


def test_an_open_stage_without_items_is_refused(tmp_path):
    """Stage 231 was a heading and nothing else for ten days."""
    result = _run(_specimen(tmp_path, "## Этап 231. Одинокий заголовок — `todo`\n"))
    assert result.returncode == 1
    assert "этап 231 открыт" in result.stdout


def test_a_closed_stage_may_be_prose_only(tmp_path):
    """26 finished stages carry no item list at all; that is not an error."""
    result = _run(_specimen(tmp_path, "## Этап 51. Только текст — `done`\n\nЧто сделали.\n"))
    assert result.returncode == 0, result.stdout


def test_commentary_after_a_blank_line_does_not_become_the_status(tmp_path):
    """An item's own paragraph decides its status; prose under it may quote any word."""
    result = _run(
        _specimen(
            tmp_path,
            "## Этап 254. Закрытый — `done`\n\n"
            "- 254.3 Сделано. — `done`\n\n"
            "  Комментарий, в котором встречается слово `todo` — это цитата,\n"
            "  а не статус пункта.\n",
        )
    )
    assert result.returncode == 0, result.stdout


def test_a_wrapped_item_keeps_the_status_on_its_last_line(tmp_path):
    result = _run(
        _specimen(
            tmp_path,
            "## Этап 235. Закрытый — `done`\n\n"
            "- 235.7 Длинный пункт, который переносится на вторую строку и\n"
            "  заканчивается статусом там. — `todo`\n",
        )
    )
    assert result.returncode == 1
    assert "пункт 235.7 остался `todo`" in result.stdout

"""Этап 302 — срок хранения логов измеряется днями, а не числом файлов.

Этап 234 обещал: «≤10 МиБ на файл и максимум 14 файлов / 14 UTC-дней». Два
ограничения писались как одно, потому что подразумевался один файл в день. Но
файл режется по размеру, и число файлов за день ничем не ограничено: 04.09.2026
на боевом сервере их получилось **пятнадцать за сутки**, и плоский лимит в 14
файлов стёр всё, что старше одного дня.

Обнаружилось это не проверкой, а по последствию: 05.09.2026 понадобилось
сопоставить события Sentry от 27.08–03.09 с остановками сервиса, и логов за те
дни уже не было — хотя политика обещала две недели.

Хранение теперь ограничивается днями и общим объёмом. Объём нужен: диск на
боевом хосте 20 ГБ и уже забивался; 14 дней по 15 файлов дали бы 2 ГБ логов.
Разница в том, что бюджет назван явно, а не подменяет собой срок хранения.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structured_logging
from structured_logging import (
    PERSISTENT_LOG_MAX_BYTES,
    PERSISTENT_LOG_MAX_TOTAL_BYTES,
    PERSISTENT_LOG_RETENTION_DAYS,
    PersistentRotatingFileHandler,
)


def _write_day(directory, day: str, count: int, size: int = 1024) -> None:
    for index in range(1, count + 1):
        (directory / f"runtime-{day}-{index:03d}.log").write_text("x" * size, encoding="utf-8")


def test_a_busy_day_does_not_erase_the_previous_ones(tmp_path) -> None:
    """Главный случай: пятнадцать файлов за сутки не должны стирать историю."""
    today = datetime.now(timezone.utc)
    for offset in range(0, 5):
        day = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        _write_day(tmp_path, day, 15 if offset == 0 else 1)

    handler = PersistentRotatingFileHandler(str(tmp_path))
    handler._prune()

    surviving_days = {path.name[8:18] for path in tmp_path.glob("runtime-*.log")}
    assert len(surviving_days) == 5, (
        f"нагруженный день съел историю: остались дни {sorted(surviving_days)}"
    )


def test_files_older_than_the_retention_window_are_removed(tmp_path) -> None:
    today = datetime.now(timezone.utc)
    old_day = (today - timedelta(days=PERSISTENT_LOG_RETENTION_DAYS + 3)).strftime("%Y-%m-%d")
    fresh_day = today.strftime("%Y-%m-%d")
    _write_day(tmp_path, old_day, 2)
    _write_day(tmp_path, fresh_day, 2)

    handler = PersistentRotatingFileHandler(str(tmp_path))
    handler._prune()

    remaining = {path.name[8:18] for path in tmp_path.glob("runtime-*.log")}
    assert remaining == {fresh_day}


def test_total_size_budget_drops_the_oldest_first(tmp_path, monkeypatch) -> None:
    """Диск ограничен, и бюджет объёма назван явно — но режет по старшинству."""
    monkeypatch.setattr(structured_logging, "PERSISTENT_LOG_MAX_TOTAL_BYTES", 3 * 1024)
    today = datetime.now(timezone.utc)
    days = [(today - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(4, -1, -1)]
    for day in days:
        _write_day(tmp_path, day, 1, size=1024)

    handler = PersistentRotatingFileHandler(str(tmp_path))
    handler._prune()

    remaining = sorted(path.name[8:18] for path in tmp_path.glob("runtime-*.log"))
    assert remaining == days[-3:], "бюджет должен срезать самые старые, а не свежие"


def test_the_budget_is_large_enough_for_the_promised_window() -> None:
    """Бюджет не должен снова тихо подменять срок хранения.

    Наблюдавшийся максимум — 15 файлов по 10 МиБ за сутки. Если бюджета не
    хватает даже на один такой день, обещание «две недели» опять станет
    неправдой, просто по другой причине.
    """
    busiest_day_bytes = 15 * PERSISTENT_LOG_MAX_BYTES

    assert PERSISTENT_LOG_MAX_TOTAL_BYTES >= busiest_day_bytes


def test_flat_file_count_limit_is_gone() -> None:
    """Именно он превращал две недели в сутки."""
    assert not hasattr(structured_logging, "PERSISTENT_LOG_MAX_FILES")

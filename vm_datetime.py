"""Vetmanager datetime boundary helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import re


_VM_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_ISO_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?$")


def normalize_vm_datetime(value: str, *, field_name: str = "datetime") -> str:
    """Normalize accepted MCP datetime input to VM's naive second-precision format."""
    raw_value = value.strip()
    if not raw_value:
        raise ValueError(f"invalid VM datetime for {field_name}: value is required")
    if _VM_DATETIME_RE.fullmatch(raw_value):
        try:
            datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S")
        except ValueError as exc:
            raise ValueError(f"invalid VM datetime for {field_name}: {value}") from exc
        return raw_value
    if not _ISO_DATETIME_RE.fullmatch(raw_value):
        raise ValueError(f"invalid VM datetime for {field_name}: {value}")
    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError(f"invalid VM datetime for {field_name}: {value}") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"invalid VM datetime for {field_name}: timezone is not supported")
    return parsed.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def day_start(day: str) -> str:
    """Начало суток для фильтра по timestamp-колонке Ветменеджера.

    Этап 293. Поля вроде `invoice.create_date` и `client.last_visit_date` —
    `timestamp`, и сравнение с голой датой означает полночь. Границы диапазона
    строятся парой `day_start(from)` / `next_day_start(to)`, чтобы диапазон
    означал сутки целиком.
    """
    return f"{date.fromisoformat(day).isoformat()} 00:00:00"


def next_day_start(day: str) -> str:
    """Начало суток, следующих за `day` — верхняя граница строгим сравнением."""
    return f"{(date.fromisoformat(day) + timedelta(days=1)).isoformat()} 00:00:00"

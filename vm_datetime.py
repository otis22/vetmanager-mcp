"""Vetmanager datetime boundary helpers."""

from __future__ import annotations

from datetime import datetime
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

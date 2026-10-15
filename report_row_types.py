"""Conservative JSON type normalization for Report AI data rows only."""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any


_NUMBER_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\Z")
_NUMERIC_NAMES = frozenset({
    "сумма", "баланс", "количество", "цена", "стоимость", "итого",
    "выручка", "долг", "остаток", "средний чек", "count", "qty",
    "amount", "balance", "price", "total", "sum", "revenue",
})
_NUMERIC_WORDS = frozenset({
    "сумма", "баланс", "количество", "цена", "стоимость", "итого",
    "выручка", "долг", "остаток", "count", "qty", "amount", "balance",
    "price", "total", "sum", "revenue",
})
_NUMERIC_TYPES = frozenset({"int", "integer", "float", "double", "decimal", "numeric", "number"})
_TEXT_TYPES = frozenset({"string", "text", "varchar", "char", "uuid", "date", "datetime"})
_PROTECTED_PARTS = ("код", "code", "артикул", "article", "телефон", "phone",
                    "sku", "barcode", "ean", "gtin", "isbn", "serial", "номер", "uuid")
_MAX_SAFE_JSON_INTEGER = 2**53 - 1


def _protected_name(name: str) -> bool:
    compact = "".join(char for char in name.casefold() if char.isalnum())
    tokens = re.split(r"[^\w]+|_", name.casefold())
    return (compact.startswith(("id", "ид")) or compact.endswith(("id", "ид"))
            or any(token in {"id", "ид"} for token in tokens)
            or any(part in compact for part in _PROTECTED_PARTS))


def _column_name_and_type(column: Any) -> tuple[str | None, str | None]:
    if isinstance(column, str):
        return column, None
    if isinstance(column, dict):
        name = column.get("name")
        kind = column.get("type")
        if isinstance(name, str):
            return name, kind if isinstance(kind, str) else ""
    return None, None


def _numeric_title(name: str) -> bool:
    lowered = name.strip().casefold()
    return lowered in _NUMERIC_NAMES or bool(set(re.findall(r"[^\W_]+", lowered)) & _NUMERIC_WORDS)


def _numeric_columns(columns: Any) -> set[str]:
    if not isinstance(columns, list):
        return set()
    decisions: dict[str, list[bool]] = {}
    for column in columns:
        name, kind = _column_name_and_type(column)
        if not name:
            continue
        normalized_kind = kind.strip().casefold() if kind is not None else None
        eligible = not _protected_name(name) and normalized_kind not in _TEXT_TYPES and (
            normalized_kind in _NUMERIC_TYPES or (
            normalized_kind is None and _numeric_title(name)
            )
        )
        decisions.setdefault(name, []).append(eligible)
    return {name for name, flags in decisions.items() if all(flags)}


def _number(value: str) -> int | float | str:
    if len(value) > 128 or not _NUMBER_RE.fullmatch(value):
        return value
    try:
        decimal = Decimal(value)
        if abs(decimal.as_tuple().exponent) > 100 or len(decimal.as_tuple().digits) > 100:
            return value
        if not decimal.is_finite() or (decimal.is_zero() and value.startswith("-")):
            return value
        if decimal == decimal.to_integral_value():
            integer = int(decimal)
            return integer if abs(integer) <= _MAX_SAFE_JSON_INTEGER else value
        floating = float(decimal)
        if math.isfinite(floating) and Decimal(str(floating)) == decimal:
            return floating
    except (InvalidOperation, OverflowError, ValueError):
        pass
    return value


def normalize_report_rows(payload: Any) -> Any:
    """Return a copy with only data.rows cells normalized; leave metadata intact."""
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return payload
    numeric = _numeric_columns(data.get("columns"))
    rows = []
    for row in data["rows"]:
        if not isinstance(row, dict):
            rows.append(row)
            continue
        rows.append({key: (None if value == "" else _number(value)
                           if key in numeric and isinstance(value, str) else value)
                     for key, value in row.items()})
    return {**payload, "data": {**data, "rows": rows}}

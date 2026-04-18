"""Typed filter builders for Vetmanager REST API `filter` query parameter.

Problem solved: raw `json.dumps([{"property": X, "value": Y, "operator": "="}])`
is repeated 15+ times across `tools/*.py` with subtle differences in operator
casing, value coercion and IN-handling. This module centralizes construction
into one typed primitive, producing the canonical dict shape via `to_dict()`.

Callers can still pass raw dicts to `validators.build_list_query_params` —
Filter objects are additive, not a breaking replacement. Migration of
existing tool callers tracked in stage 93b.

Usage:
    from filters import eq, in_, like

    filters = [eq("status", "ACTIVE"), in_("id", [1, 2, 3]), like("alias", "Rex%")]
    params = build_list_query_params(limit=20, filters=filters)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any


class FilterOp(str, Enum):
    """Supported operators for VM REST filter clauses.

    The VM backend accepts mixed case (`"IN"` / `"in"`) per stage 82/83
    probe; we emit uppercase canonical form everywhere.
    """

    EQ = "="
    NE = "!="
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"


@dataclass(frozen=True)
class Filter:
    """One filter clause for VM REST API.

    Produces the canonical dict shape `{"property", "value", "operator"}`
    accepted by the `filter` query parameter.
    """

    property: str
    value: Any
    operator: FilterOp

    def to_dict(self) -> dict[str, Any]:
        return {
            "property": self.property,
            "value": self.value,
            "operator": self.operator.value,
        }


def eq(property: str, value: Any) -> Filter:
    """property == value."""
    return Filter(property=property, value=value, operator=FilterOp.EQ)


def ne(property: str, value: Any) -> Filter:
    """property != value."""
    return Filter(property=property, value=value, operator=FilterOp.NE)


def lt(property: str, value: Any) -> Filter:
    """property < value."""
    return Filter(property=property, value=value, operator=FilterOp.LT)


def lte(property: str, value: Any) -> Filter:
    """property <= value."""
    return Filter(property=property, value=value, operator=FilterOp.LTE)


def gt(property: str, value: Any) -> Filter:
    """property > value."""
    return Filter(property=property, value=value, operator=FilterOp.GT)


def gte(property: str, value: Any) -> Filter:
    """property >= value."""
    return Filter(property=property, value=value, operator=FilterOp.GTE)


def in_(property: str, values: list[Any]) -> Filter:
    """property IN (v1, v2, ...).

    Values list is preserved as-is — the VM API parses JSON array directly
    without further coercion. Callers should pre-stringify if the entity
    expects string-typed ids.

    Empty lists are rejected (stage 96.5): VM API semantics for `IN []` are
    undefined — some endpoints return 500, some treat as match-all. Callers
    must explicitly handle the no-matches short-circuit before building the
    filter.
    """
    if not isinstance(values, (list, tuple)):
        raise TypeError(
            f"in_ requires a list/tuple of values, got {type(values).__name__}"
        )
    if not values:
        raise ValueError(
            "in_ requires at least one value; VM API behavior on IN [] is undefined. "
            "Short-circuit the no-matches case in the caller."
        )
    return Filter(property=property, value=list(values), operator=FilterOp.IN)


def not_in(property: str, values: list[Any]) -> Filter:
    """property NOT IN (v1, v2, ...). Empty lists rejected (see in_)."""
    if not isinstance(values, (list, tuple)):
        raise TypeError(
            f"not_in requires a list/tuple of values, got {type(values).__name__}"
        )
    if not values:
        raise ValueError(
            "not_in requires at least one value; VM API behavior on NOT IN [] is undefined."
        )
    return Filter(property=property, value=list(values), operator=FilterOp.NOT_IN)


def like(property: str, pattern: str) -> Filter:
    """property LIKE pattern (SQL % wildcards)."""
    return Filter(property=property, value=pattern, operator=FilterOp.LIKE)


def as_dict_list(filters: list[Filter] | list[dict] | None) -> list[dict] | None:
    """Normalize a mixed list of Filter objects and/or raw dicts to dicts.

    Passes raw dicts through unchanged to support gradual caller migration.
    Returns None for empty/None input so callers can omit the filter param.
    """
    if not filters:
        return None
    result: list[dict] = []
    for item in filters:
        if isinstance(item, Filter):
            result.append(item.to_dict())
        elif isinstance(item, dict):
            result.append(item)
        else:
            raise TypeError(
                f"filter items must be Filter or dict, got {type(item).__name__}"
            )
    return result


def build_list_query_params(
    limit: int,
    offset: int,
    sort: list[dict[str, Any]] | None = None,
    filters: list[dict[str, Any]] | list[Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build common list-query params with optional sort/filter blocks.

    `filters` may be a list of raw dicts (legacy callers) OR a list of
    `Filter` objects (typed builder). Mixed lists are also accepted.

    Stage 103.8: moved from `validators.py` — sits next to the filter
    primitives it serializes, eliminates the previous lazy import back to
    `filters.as_dict_list`.
    """
    # Lazy import avoids pulling pydantic at filter-module import time.
    from validators import validate_list_params

    validate_list_params(limit, offset)
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if sort:
        params["sort"] = json.dumps(sort, separators=(",", ":"), ensure_ascii=False)
    if filters:
        normalized = as_dict_list(filters)
        if normalized:
            params["filter"] = json.dumps(
                normalized, separators=(",", ":"), ensure_ascii=False
            )

    if extra:
        for key, value in extra.items():
            # Stage 106.4 (F6 fix): skip only None and empty string.
            # Previously also dropped numeric zero, which silently converted
            # `extra={"client_id": 0}` into an UNFILTERED query (full-table
            # scan, privacy risk). Callers wanting to omit a default value
            # should filter at the call site explicitly.
            if value is None or value == "":
                continue
            params[key] = value

    return params

"""Thin CRUD helpers that eliminate boilerplate in tool modules.

Each helper encapsulates VetmanagerClient instantiation and the HTTP call.
Tool functions keep their own @mcp.tool decorators, docstrings, signatures,
and payload-building logic — only the final HTTP invocation is delegated here.

All CRUD calls are instrumented — endpoint+method serve as a per-tool
proxy label for `vetmanager_tool_call_latency_seconds` and
`vetmanager_tool_calls_total{outcome=success|error}`.
"""

import json
from functools import cmp_to_key
from typing import Any, TypeVar

from exceptions import ToolInputError, reportable_error
from filters import (
    as_dict_list, build_list_query_params, validate_filter_properties,
    validate_sort_properties,
)
from service_metrics import instrument_call as _instrumented_call
from vetmanager_client import VetmanagerClient

T = TypeVar("T")

# Stage 103.6: _instrumented_call is now canonical in service_metrics.
# This re-export preserves backward compatibility for any future caller
# (and for tests that may import _instrumented_call from crud_helpers).


def total_order_sort(
    sort: list[dict] | None,
    allowed_properties: frozenset[str] | None = None,
) -> list[dict]:
    """Validate a sort and append a unique id tie-breaker when absent."""
    if allowed_properties is not None:
        validate_sort_properties(sort, allowed_properties)
    normalized: list[dict] = []
    for item in sort or []:
        if not isinstance(item, dict) or not isinstance(item.get("property"), str):
            raise ToolInputError("Each sort item must contain a property")
        direction = str(item.get("direction", "ASC")).upper()
        if direction not in {"ASC", "DESC"}:
            raise ToolInputError("Sort direction must be ASC or DESC")
        normalized.append({"property": item["property"], "direction": direction})
    if not any(item["property"] == "id" for item in normalized):
        normalized.append({"property": "id", "direction": "ASC"})
    return normalized


def _sortable_value(value: object) -> tuple:
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (1, float(value))
    if isinstance(value, str):
        return (2, value.casefold(), value)
    return (3, type(value).__name__, str(value))


def sort_records(records: list[dict], sort: list[dict]) -> list[dict]:
    """Sort merged API rows deterministically, keeping null values last."""
    def compare(left: dict, right: dict) -> int:
        for item in sort:
            left_value = left.get(item["property"])
            right_value = right.get(item["property"])
            if left_value is None or right_value is None:
                result = (left_value is None) - (right_value is None)
            else:
                left_key = _sortable_value(left_value)
                right_key = _sortable_value(right_value)
                result = (left_key > right_key) - (left_key < right_key)
                if item["direction"] == "DESC":
                    result = -result
            if result:
                return result
        return 0

    return sorted(records, key=cmp_to_key(compare))


def normalize_record_id(value: object, *, label: str) -> int:
    """Return an upstream integer-like record id or fail closed."""
    if isinstance(value, bool):
        raise reportable_error(f"invalid record id in {label} response")
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    raise reportable_error(f"invalid record id in {label} response")


def extract_list_page(
    response: object,
    *,
    endpoint: str,
    entity_key: str,
) -> tuple[list[dict], int | None]:
    """Validate one successful list envelope without leaking its message."""
    if not isinstance(response, dict) or response.get("success") is not True:
        raise reportable_error(f"upstream list request failed for {endpoint}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise reportable_error(f"malformed upstream list response for {endpoint}")
    records = data.get(entity_key)
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise reportable_error(f"malformed {entity_key} rows from {endpoint}")
    raw_total = data.get("totalCount")
    total = (
        raw_total
        if isinstance(raw_total, int) and not isinstance(raw_total, bool) and raw_total >= 0
        else None
    )
    return records, total


def unwrap_single_record(response: dict, *entity_keys: str) -> dict | None:
    """Return one entity record from a Vetmanager GET-by-id response.

    Controllers do not consistently case their singleton container keys
    (for example, ``medicalCards`` versus ``admission``).  Callers provide
    the API-confirmed key(s), avoiding an unsafe fallback to response metadata.
    """
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        return None
    for entity_key in entity_keys:
        record = data.get(entity_key)
        if isinstance(record, dict):
            return record
    return None


async def crud_list(
    endpoint: str,
    *,
    limit: int,
    offset: int,
    sort: list[dict] | None = None,
    filters: list[dict] | None = None,
    extra: dict[str, Any] | None = None,
    allowed_filter_properties: frozenset[str] | None = None,
) -> dict:
    """Build query params and GET a list endpoint."""
    if allowed_filter_properties is not None:
        validate_filter_properties(filters, allowed_filter_properties)
        validate_sort_properties(sort, allowed_filter_properties)
    params = build_list_query_params(
        limit=limit,
        offset=offset,
        sort=sort,
        filters=filters,
        extra=extra,
    )
    return await _instrumented_call(
        endpoint,
        "GET",
        lambda: VetmanagerClient().get(endpoint, params=params),
        operation="list",
    )


async def crud_get_by_id(endpoint: str, entity_id: int) -> dict:
    """GET a single entity by ID."""
    return await _instrumented_call(
        endpoint,
        "GET",
        lambda: VetmanagerClient().get(f"{endpoint}/{entity_id}"),
        operation="get_by_id",
    )


async def crud_create(endpoint: str, payload: dict) -> dict:
    """POST a new entity."""
    return await _instrumented_call(
        endpoint,
        "POST",
        lambda: VetmanagerClient().post(endpoint, json=payload),
        operation="create",
    )


async def crud_update(endpoint: str, entity_id: int, payload: dict) -> dict:
    """PUT an updated entity."""
    return await _instrumented_call(
        endpoint,
        "PUT",
        lambda: VetmanagerClient().put(f"{endpoint}/{entity_id}", json=payload),
        operation="update",
    )


async def crud_delete(endpoint: str, entity_id: int) -> dict:
    """DELETE an entity by ID."""
    return await _instrumented_call(
        endpoint,
        "DELETE",
        lambda: VetmanagerClient().delete(f"{endpoint}/{entity_id}"),
        operation="delete",
    )


async def paginate_all(
    endpoint: str,
    *,
    filters: list | None = None,
    extra: dict[str, Any] | None = None,
    sort: list[dict] | None = None,
    allowed_filter_properties: frozenset[str] | None = None,
    page_size: int = 100,
    entity_key: str,
    max_rows: int | None = 10_000,
    max_calls: int = 1_000,
) -> tuple[list[dict], int]:
    """Fetch all pages of a list endpoint.

    Args:
        extra: Query parameters repeated unchanged on every page.
        max_rows: Hard cap on total rows fetched (default 10_000). Raises
            ToolError if totalCount (or collected rows) exceeds the cap —
            prevents runaway memory use on pathologically large result sets.
            Pass `None` to disable the cap (only for operationally-bounded
            callers that know the result set is limited by other constraints).

    Returns:
        Tuple of (all_records, total_count).
    """
    vc = VetmanagerClient()
    all_records: list[dict] = []
    offset = 0
    calls = 0
    seen_full_pages: set[str] = set()
    effective_sort = total_order_sort(sort, allowed_filter_properties)

    normalized_filters = as_dict_list(filters) if filters else None
    if allowed_filter_properties is not None:
        validate_filter_properties(filters, allowed_filter_properties)

    while True:
        if calls >= max_calls:
            raise reportable_error(
                f"pagination call budget exceeded for {endpoint}; narrow filters"
            )
        params = build_list_query_params(
            limit=page_size,
            offset=offset,
            sort=effective_sort,
            filters=normalized_filters,
            extra=extra,
        )

        resp = await vc.get(endpoint, params=params)
        calls += 1
        records, page_total_count = extract_list_page(
            resp, endpoint=endpoint, entity_key=entity_key,
        )

        if max_rows is not None and page_total_count is not None and page_total_count > max_rows:
            raise reportable_error(
                f"result set too large for {endpoint}: totalCount={page_total_count} "
                f"exceeds max_rows={max_rows}. Narrow your date range or filters."
            )

        if not records:
            if page_total_count is not None and offset < page_total_count:
                raise reportable_error(
                    f"pagination ended before totalCount for {endpoint}"
                )
            break

        if len(records) >= page_size:
            fingerprint = json.dumps(records, sort_keys=True, default=str, separators=(",", ":"))
            if fingerprint in seen_full_pages:
                raise reportable_error(
                    f"pagination made no progress for {endpoint}"
                )
            seen_full_pages.add(fingerprint)

        all_records.extend(records)
        offset += len(records)

        if max_rows is not None and len(all_records) > max_rows:
            raise reportable_error(
                f"result set too large for {endpoint}: accumulated "
                f"{len(all_records)} rows exceeds max_rows={max_rows}. "
                "Narrow your date range or filters."
            )

        if (
            len(records) < page_size
            and (page_total_count is None or offset >= page_total_count)
        ):
            break

    return all_records, len(all_records)

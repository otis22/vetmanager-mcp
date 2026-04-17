"""Thin CRUD helpers that eliminate boilerplate in tool modules.

Each helper encapsulates VetmanagerClient instantiation and the HTTP call.
Tool functions keep their own @mcp.tool decorators, docstrings, signatures,
and payload-building logic — only the final HTTP invocation is delegated here.

All CRUD calls are instrumented — endpoint+method serve as a per-tool
proxy label for `vetmanager_tool_call_latency_seconds` and
`vetmanager_tool_calls_total{outcome=success|error}`.
"""

import json
import time
from typing import Any, Awaitable, Callable, TypeVar

from service_metrics import record_tool_call
from validators import build_list_query_params
from vetmanager_client import VetmanagerClient

T = TypeVar("T")


async def _instrumented_call(
    endpoint: str,
    method: str,
    coro_factory: Callable[[], Awaitable[T]],
) -> T:
    """Wrap a single tool call, record latency + outcome metric."""
    started = time.monotonic()
    outcome = "success"
    try:
        return await coro_factory()
    except BaseException:
        # BaseException (not Exception) so asyncio.CancelledError also marks
        # the call as non-success — a cancelled tool call is not a completed
        # successful call and should not skew outcome metrics.
        outcome = "error"
        raise
    finally:
        elapsed = time.monotonic() - started
        record_tool_call(
            endpoint=endpoint,
            method=method,
            outcome=outcome,
            duration_seconds=elapsed,
        )


async def crud_list(
    endpoint: str,
    *,
    limit: int,
    offset: int,
    sort: list[dict] | None = None,
    filters: list[dict] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict:
    """Build query params and GET a list endpoint."""
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
    )


async def crud_get_by_id(endpoint: str, entity_id: int) -> dict:
    """GET a single entity by ID."""
    return await _instrumented_call(
        endpoint,
        "GET",
        lambda: VetmanagerClient().get(f"{endpoint}/{entity_id}"),
    )


async def crud_create(endpoint: str, payload: dict) -> dict:
    """POST a new entity."""
    return await _instrumented_call(
        endpoint,
        "POST",
        lambda: VetmanagerClient().post(endpoint, json=payload),
    )


async def crud_update(endpoint: str, entity_id: int, payload: dict) -> dict:
    """PUT an updated entity."""
    return await _instrumented_call(
        endpoint,
        "PUT",
        lambda: VetmanagerClient().put(f"{endpoint}/{entity_id}", json=payload),
    )


async def crud_delete(endpoint: str, entity_id: int) -> dict:
    """DELETE an entity by ID."""
    return await _instrumented_call(
        endpoint,
        "DELETE",
        lambda: VetmanagerClient().delete(f"{endpoint}/{entity_id}"),
    )


async def paginate_all(
    endpoint: str,
    *,
    filters: list[dict] | None = None,
    page_size: int = 100,
    entity_key: str,
    max_rows: int | None = 10_000,
) -> tuple[list[dict], int]:
    """Fetch all pages of a list endpoint.

    Args:
        max_rows: Hard cap on total rows fetched (default 10_000). Raises
            ValueError if totalCount (or collected rows) exceeds the cap —
            prevents runaway memory use on pathologically large result sets.
            Pass `None` to disable the cap (only for operationally-bounded
            callers that know the result set is limited by other constraints).

    Returns:
        Tuple of (all_records, total_count).
    """
    vc = VetmanagerClient()
    all_records: list[dict] = []
    offset = 0

    filter_str: str | None = None
    if filters:
        filter_str = json.dumps(filters, separators=(",", ":"))

    while True:
        params: dict[str, Any] = {"limit": page_size, "offset": offset}
        if filter_str:
            params["filter"] = filter_str

        resp = await vc.get(endpoint, params=params)
        data = resp.get("data", {})
        total_count = int(data.get("totalCount", 0)) if isinstance(data, dict) else 0
        records = data.get(entity_key, []) if isinstance(data, dict) else []

        if max_rows is not None and total_count > max_rows:
            raise ValueError(
                f"result set too large for {endpoint}: totalCount={total_count} "
                f"exceeds max_rows={max_rows}. Narrow your date range or filters."
            )

        if not records:
            break

        all_records.extend(records)
        offset += len(records)

        if max_rows is not None and len(all_records) > max_rows:
            raise ValueError(
                f"result set too large for {endpoint}: accumulated "
                f"{len(all_records)} rows exceeds max_rows={max_rows}. "
                "Narrow your date range or filters."
            )

        if offset >= total_count or len(records) < page_size:
            break

    return all_records, total_count

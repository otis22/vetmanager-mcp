"""Process-local service metrics registry for observability stages."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from threading import Lock
from typing import DefaultDict

from observability_logging import RUNTIME_LOGGER

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@dataclass(slots=True)
class LatencyAggregate:
    """Aggregate latency statistics for one labeled operation."""

    count: int = 0
    sum_seconds: float = 0.0
    max_seconds: float = 0.0

    def observe(self, duration_seconds: float) -> None:
        self.count += 1
        self.sum_seconds += duration_seconds
        self.max_seconds = max(self.max_seconds, duration_seconds)


_LOCK = Lock()
_HTTP_REQUESTS_TOTAL: DefaultDict[tuple[str, str, int], int] = defaultdict(int)
_HTTP_REQUEST_LATENCY_SECONDS: DefaultDict[tuple[str, str], LatencyAggregate] = defaultdict(
    LatencyAggregate
)
_AUTH_FAILURES_TOTAL: DefaultDict[tuple[str, str], int] = defaultdict(int)
_UPSTREAM_FAILURES_TOTAL: DefaultDict[tuple[str, str], int] = defaultdict(int)
_UPSTREAM_REQUESTS_TOTAL: DefaultDict[tuple[str, str], int] = defaultdict(int)
_UPSTREAM_LATENCY_SECONDS: DefaultDict[tuple[str, str], LatencyAggregate] = defaultdict(
    LatencyAggregate
)
_TOOL_CALLS_TOTAL: DefaultDict[tuple[str, str, str], int] = defaultdict(int)
_TOOL_CALL_LATENCY_SECONDS: DefaultDict[tuple[str, str], LatencyAggregate] = defaultdict(
    LatencyAggregate
)
# Stage 110.2: business events counter — `account_registered`, `bearer_token_issued`,
# `bearer_token_revoked`, `web_login_succeeded`. Accumulated in-process since last
# reset; reset_service_metrics() zeros it. Persistent counts live in the DB
# (TokenUsageLog + Account); this metric is the hook for future Grafana panels
# without touching the call sites again.
_BUSINESS_EVENTS_TOTAL: DefaultDict[str, int] = defaultdict(int)


def reset_service_metrics() -> None:
    """Clear all in-memory metrics. Tests should call this to isolate assertions."""
    with _LOCK:
        _HTTP_REQUESTS_TOTAL.clear()
        _HTTP_REQUEST_LATENCY_SECONDS.clear()
        _AUTH_FAILURES_TOTAL.clear()
        _UPSTREAM_FAILURES_TOTAL.clear()
        _UPSTREAM_REQUESTS_TOTAL.clear()
        _UPSTREAM_LATENCY_SECONDS.clear()
        _TOOL_CALLS_TOTAL.clear()
        _TOOL_CALL_LATENCY_SECONDS.clear()
        _BUSINESS_EVENTS_TOTAL.clear()


_ALLOWED_BUSINESS_EVENTS = frozenset({
    "account_registered",
    "web_login_succeeded",
    "bearer_token_issued",
    "bearer_token_revoked",
})


def record_business_event(event_name: str) -> None:
    """Increment the business-event counter (stage 110.2).

    Called from registration, token issuance/revocation, and login success
    handlers. Snapshot is exposed via `snapshot_service_metrics()["business_events_total"]`
    and the Prometheus `/metrics` endpoint for future dashboards.

    Strict allowlist: unexpected `event_name` values are rejected (prevents
    cardinality blow-ups from typos or dynamic strings). Stage 111.4 (F6
    super-review 2026-04-19): rejection now emits an ERROR log so typos
    in new call-sites surface immediately instead of silently flat-lining
    the metric.
    """
    if event_name not in _ALLOWED_BUSINESS_EVENTS:
        RUNTIME_LOGGER.error(
            "record_business_event: unknown event_name dropped",
            extra={
                "event_name": "business_event_unknown",
                "dropped_name": event_name,
            },
        )
        return
    with _LOCK:
        _BUSINESS_EVENTS_TOTAL[event_name] += 1


def record_http_request(*, route: str, method: str, status_code: int, duration_seconds: float) -> None:
    """Record one observed HTTP request outcome and latency."""
    normalized_method = method.upper()
    with _LOCK:
        _HTTP_REQUESTS_TOTAL[(route, normalized_method, status_code)] += 1
        _HTTP_REQUEST_LATENCY_SECONDS[(route, normalized_method)].observe(duration_seconds)


def record_auth_failure(*, source: str, reason: str) -> None:
    """Record an auth failure grouped by source and machine-readable reason."""
    with _LOCK:
        _AUTH_FAILURES_TOTAL[(source, reason)] += 1


def record_upstream_failure(*, target: str, reason: str) -> None:
    """Record a failed upstream interaction grouped by target and reason."""
    with _LOCK:
        _UPSTREAM_FAILURES_TOTAL[(target, reason)] += 1


def record_upstream_request(
    *, target: str, status: str, duration_seconds: float
) -> None:
    """Record one upstream (external API) interaction with its latency.

    Unlike record_upstream_failure (counters for failures by reason),
    this captures BOTH success and failure outcomes with duration so
    SRE can compute p95 / error rate on external calls.
    """
    with _LOCK:
        _UPSTREAM_REQUESTS_TOTAL[(target, status)] += 1
        _UPSTREAM_LATENCY_SECONDS[(target, status)].observe(duration_seconds)


async def instrument_call(
    endpoint: str,
    method: str,
    coro_factory,
    *,
    operation: str = "",
    tool_name: str | None = None,
):
    """Wrap a coroutine with latency + outcome metric recording.

    Stage 103.6: moved from tools.crud_helpers so non-CRUD callers (web
    handlers, future gateway layer) can use the same instrumentation
    without importing crud_helpers.

    Stage 107.6 (obs F6 fix): optional `tool_name` label. Without it,
    all `/rest/api/client` calls collide in Prometheus — aggregator
    `get_client_profile` p95 mixes with CRUD `get_clients` list p95.
    Pass `tool_name="get_client_profile"` at the aggregator boundary
    to get a distinct time series.
    """
    import time as _time
    started = _time.monotonic()
    outcome = "success"
    endpoint_label = f"{endpoint}#{operation}" if operation else endpoint
    try:
        return await coro_factory()
    except BaseException:
        outcome = "error"
        raise
    finally:
        elapsed = _time.monotonic() - started
        record_tool_call(
            endpoint=endpoint_label,
            method=method,
            outcome=outcome,
            duration_seconds=elapsed,
            tool_name=tool_name,
        )


def record_tool_call(
    *,
    endpoint: str,
    method: str,
    outcome: str,
    duration_seconds: float,
    tool_name: str | None = None,
) -> None:
    """Record one MCP tool invocation with its outcome and latency.

    `endpoint` is the VM REST path (e.g. `/rest/api/client`), `method` is
    the HTTP verb, `outcome` is `"success"` or `"error"`.

    Stage 107.6: optional `tool_name` label. If present, appended to the
    endpoint key as `endpoint:tool_name` so aggregator tools get a
    distinct series vs CRUD tools on the same VM endpoint.
    """
    normalized_method = method.upper()
    labeled_endpoint = f"{endpoint}:{tool_name}" if tool_name else endpoint
    with _LOCK:
        _TOOL_CALLS_TOTAL[(labeled_endpoint, normalized_method, outcome)] += 1
        _TOOL_CALL_LATENCY_SECONDS[(labeled_endpoint, normalized_method)].observe(
            duration_seconds
        )


def snapshot_service_metrics() -> dict[str, dict[str, int | float | dict[str, int | float]]]:
    """Return a stable JSON-serializable snapshot of current service metrics."""
    with _LOCK:
        return {
            "http_requests_total": {
                f"{route}|{method}|{status_code}": count
                for (route, method, status_code), count in sorted(_HTTP_REQUESTS_TOTAL.items())
            },
            "http_request_latency_seconds": {
                f"{route}|{method}": asdict(aggregate)
                for (route, method), aggregate in sorted(_HTTP_REQUEST_LATENCY_SECONDS.items())
            },
            "auth_failures_total": {
                f"{source}|{reason}": count
                for (source, reason), count in sorted(_AUTH_FAILURES_TOTAL.items())
            },
            "upstream_failures_total": {
                f"{target}|{reason}": count
                for (target, reason), count in sorted(_UPSTREAM_FAILURES_TOTAL.items())
            },
            "upstream_requests_total": {
                f"{target}|{status}": count
                for (target, status), count in sorted(_UPSTREAM_REQUESTS_TOTAL.items())
            },
            "upstream_request_latency_seconds": {
                f"{target}|{status}": asdict(aggregate)
                for (target, status), aggregate in sorted(_UPSTREAM_LATENCY_SECONDS.items())
            },
            "tool_calls_total": {
                f"{endpoint}|{method}|{outcome}": count
                for (endpoint, method, outcome), count in sorted(_TOOL_CALLS_TOTAL.items())
            },
            "tool_call_latency_seconds": {
                f"{endpoint}|{method}": asdict(aggregate)
                for (endpoint, method), aggregate in sorted(_TOOL_CALL_LATENCY_SECONDS.items())
            },
            "business_events_total": dict(sorted(_BUSINESS_EVENTS_TOTAL.items())),
        }


def _escape_label_value(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _labels_text(**labels: object) -> str:
    serialized = ",".join(
        f'{name}="{_escape_label_value(value)}"'
        for name, value in labels.items()
    )
    return f"{{{serialized}}}"


def render_prometheus_metrics() -> str:
    """Render current registry snapshot in Prometheus text exposition format."""
    snapshot = snapshot_service_metrics()
    lines = [
        "# HELP vetmanager_http_requests_total Total observed HTTP requests by route, method, and status code.",
        "# TYPE vetmanager_http_requests_total counter",
    ]
    for key, value in snapshot["http_requests_total"].items():
        route, method, status_code = key.split("|", 2)
        lines.append(
            f"vetmanager_http_requests_total"
            f"{_labels_text(route=route, method=method, status_code=status_code)} {value}"
        )

    lines.extend(
        [
            "# HELP vetmanager_http_request_latency_seconds Request latency aggregates for observed HTTP routes.",
            "# TYPE vetmanager_http_request_latency_seconds summary",
            "# HELP vetmanager_http_request_latency_seconds_max Maximum observed HTTP request latency by route and method.",
            "# TYPE vetmanager_http_request_latency_seconds_max gauge",
        ]
    )
    for key, value in snapshot["http_request_latency_seconds"].items():
        route, method = key.split("|", 1)
        labels = _labels_text(route=route, method=method)
        lines.append(f"vetmanager_http_request_latency_seconds_count{labels} {value['count']}")
        lines.append(f"vetmanager_http_request_latency_seconds_sum{labels} {value['sum_seconds']}")
        lines.append(f"vetmanager_http_request_latency_seconds_max{labels} {value['max_seconds']}")

    lines.extend(
        [
            "# HELP vetmanager_auth_failures_total Total auth failures by source and reason.",
            "# TYPE vetmanager_auth_failures_total counter",
        ]
    )
    for key, value in snapshot["auth_failures_total"].items():
        source, reason = key.split("|", 1)
        lines.append(
            f"vetmanager_auth_failures_total"
            f"{_labels_text(source=source, reason=reason)} {value}"
        )

    lines.extend(
        [
            "# HELP vetmanager_upstream_failures_total Total upstream failures by target and reason.",
            "# TYPE vetmanager_upstream_failures_total counter",
        ]
    )
    for key, value in snapshot["upstream_failures_total"].items():
        target, reason = key.split("|", 1)
        lines.append(
            f"vetmanager_upstream_failures_total"
            f"{_labels_text(target=target, reason=reason)} {value}"
        )

    lines.extend(
        [
            "# HELP vetmanager_upstream_requests_total Total upstream requests by target and status.",
            "# TYPE vetmanager_upstream_requests_total counter",
        ]
    )
    for key, value in snapshot["upstream_requests_total"].items():
        target, status = key.split("|", 1)
        lines.append(
            f"vetmanager_upstream_requests_total"
            f"{_labels_text(target=target, status=status)} {value}"
        )

    lines.extend(
        [
            "# HELP vetmanager_upstream_request_latency_seconds Upstream request latency by target and status.",
            "# TYPE vetmanager_upstream_request_latency_seconds summary",
        ]
    )
    for key, value in snapshot["upstream_request_latency_seconds"].items():
        target, status = key.split("|", 1)
        labels = _labels_text(target=target, status=status)
        lines.append(f"vetmanager_upstream_request_latency_seconds_count{labels} {value['count']}")
        lines.append(f"vetmanager_upstream_request_latency_seconds_sum{labels} {value['sum_seconds']}")
        lines.append(f"vetmanager_upstream_request_latency_seconds_max{labels} {value['max_seconds']}")

    lines.extend(
        [
            "# HELP vetmanager_tool_calls_total Total MCP tool invocations by endpoint, method, outcome.",
            "# TYPE vetmanager_tool_calls_total counter",
        ]
    )
    for key, value in snapshot["tool_calls_total"].items():
        endpoint, method, outcome = key.split("|", 2)
        lines.append(
            f"vetmanager_tool_calls_total"
            f"{_labels_text(endpoint=endpoint, method=method, outcome=outcome)} {value}"
        )

    lines.extend(
        [
            "# HELP vetmanager_tool_call_latency_seconds MCP tool latency by endpoint and method.",
            "# TYPE vetmanager_tool_call_latency_seconds summary",
        ]
    )
    for key, value in snapshot["tool_call_latency_seconds"].items():
        endpoint, method = key.split("|", 1)
        labels = _labels_text(endpoint=endpoint, method=method)
        lines.append(f"vetmanager_tool_call_latency_seconds_count{labels} {value['count']}")
        lines.append(f"vetmanager_tool_call_latency_seconds_sum{labels} {value['sum_seconds']}")
        lines.append(f"vetmanager_tool_call_latency_seconds_max{labels} {value['max_seconds']}")

    # Stage 110.2: business events counter for product dashboard.
    # `_labels_text` escapes backslash + double-quote per Prometheus text
    # format — safe even if a future caller passes an event_name with
    # unusual characters. Newline injection is not possible because we
    # do not include newlines in event_name values ourselves.
    lines.extend(
        [
            "# HELP vetmanager_business_events_total Business lifecycle events (account_registered, bearer_token_issued, bearer_token_revoked, web_login_succeeded).",
            "# TYPE vetmanager_business_events_total counter",
        ]
    )
    for event_name, count in snapshot.get("business_events_total", {}).items():
        lines.append(
            f"vetmanager_business_events_total{_labels_text(event=event_name)} {count}"
        )

    # Cache metrics (from request_cache singleton).
    from request_cache import REQUEST_CACHE

    m = REQUEST_CACHE.metrics
    lines.extend([
        "# HELP vetmanager_cache_hits_total Total cache hits.",
        "# TYPE vetmanager_cache_hits_total counter",
        f"vetmanager_cache_hits_total {m.hits}",
        "# HELP vetmanager_cache_misses_total Total cache misses.",
        "# TYPE vetmanager_cache_misses_total counter",
        f"vetmanager_cache_misses_total {m.misses}",
        "# HELP vetmanager_cache_invalidations_total Total cache tag invalidations.",
        "# TYPE vetmanager_cache_invalidations_total counter",
        f"vetmanager_cache_invalidations_total {m.invalidations}",
        "# HELP vetmanager_cache_evictions_total Total LRU cache evictions.",
        "# TYPE vetmanager_cache_evictions_total counter",
        f"vetmanager_cache_evictions_total {m.evictions}",
        "# HELP vetmanager_cache_entries Current number of cached entries.",
        "# TYPE vetmanager_cache_entries gauge",
        f"vetmanager_cache_entries {REQUEST_CACHE.size}",
    ])

    return "\n".join(lines) + "\n"

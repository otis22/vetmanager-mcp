"""Process-local service metrics registry for observability stages."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from threading import Lock
from typing import DefaultDict

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


def reset_service_metrics() -> None:
    """Clear all in-memory metrics. Tests should call this to isolate assertions."""
    with _LOCK:
        _HTTP_REQUESTS_TOTAL.clear()
        _HTTP_REQUEST_LATENCY_SECONDS.clear()
        _AUTH_FAILURES_TOTAL.clear()
        _UPSTREAM_FAILURES_TOTAL.clear()


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

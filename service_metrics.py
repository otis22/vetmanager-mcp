"""Process-local service metrics registry for observability stages."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from threading import Lock
from typing import DefaultDict


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

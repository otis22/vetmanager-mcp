"""Typed, low-cardinality classification for upstream transport errors."""

from __future__ import annotations

import httpx


def classify_transport_error(exc: httpx.RequestError) -> str:
    """Return a stable transport reason without inspecting exception text."""
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    return "network_error"


def classify_http_status(status_code: int) -> str:
    """Collapse status codes into bounded failure classes."""
    return "http_4xx" if 400 <= status_code < 500 else "http_5xx"

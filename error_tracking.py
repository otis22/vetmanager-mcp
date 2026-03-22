"""Optional error tracking bootstrap for production runtimes."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.starlette import StarletteIntegration

SUPPORTED_ERROR_TRACKING_BACKENDS = {"sentry"}
_REDACTED = "[Filtered]"
_SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-rest-api-key",
    "x-api-key",
}


def _resolve_release() -> str:
    configured_release = (os.environ.get("ERROR_TRACKING_RELEASE") or "").strip()
    if configured_release:
        return configured_release
    try:
        package_version = version("vetmanager-mcp")
    except PackageNotFoundError:
        package_version = "unknown"
    return f"vetmanager-mcp@{package_version}"


def _sanitize_event(event: dict[str, Any], hint: dict[str, Any] | None) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: (_REDACTED if key.lower() in _SENSITIVE_HEADER_NAMES else value)
                for key, value in headers.items()
            }
    return event


def configure_error_tracking() -> bool:
    """Initialize optional error tracking backend if runtime config is present."""
    dsn = (os.environ.get("ERROR_TRACKING_DSN") or os.environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        return False

    backend = (os.environ.get("ERROR_TRACKING_BACKEND") or "sentry").strip().lower()
    if backend not in SUPPORTED_ERROR_TRACKING_BACKENDS:
        raise RuntimeError(f"Unsupported error tracking backend: {backend}")

    traces_sample_rate = float((os.environ.get("ERROR_TRACKING_TRACES_SAMPLE_RATE") or "0").strip())
    sentry_sdk.init(
        dsn=dsn,
        environment=(os.environ.get("ERROR_TRACKING_ENVIRONMENT") or "production").strip(),
        release=_resolve_release(),
        send_default_pii=False,
        traces_sample_rate=traces_sample_rate,
        integrations=[StarletteIntegration()],
        before_send=_sanitize_event,
    )
    return True

"""Optional error tracking bootstrap for production runtimes."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.starlette import StarletteIntegration

SUPPORTED_ERROR_TRACKING_BACKENDS = {"sentry"}
_REDACTED = "[Filtered]"

# Substrings matched case-insensitively against header/cookie/body keys.
# Any key containing one of these is replaced with _REDACTED.
_SENSITIVE_KEY_PATTERNS = (
    "token", "key", "secret", "auth", "api", "cookie", "bearer", "password",
    "credential", "session", "csrf",
    # Webhook/HMAC/JWT ecosystem (Stripe, GitHub, Slack webhooks etc.)
    "signature", "jwt", "hmac", "otp", "passphrase",
)

# Exact allowlist of keys that would match a sensitive pattern but are
# actually safe to keep (observability metadata, not credentials).
# Lowered before comparison.
_SAFE_KEY_WHITELIST = frozenset({
    "x-request-id",
    "x-correlation-id",
    "x-request-ip",
    "user-agent",
    "content-type",
    "content-length",
    "accept",
    "accept-encoding",
    "accept-language",
    "host",
    "referer",
    # `api`-substring false positives: version/protocol metadata, not creds.
    "api-version",
    "x-api-version",
    "api_version",
    # Generic HTTP response metadata occasionally echoed into events.
    "retry-after",
    "location",
    "date",
    "server",
    "etag",
    "if-none-match",
    "if-modified-since",
})


def _is_sensitive_key(name: object) -> bool:
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    if lowered in _SAFE_KEY_WHITELIST:
        return False
    return any(pattern in lowered for pattern in _SENSITIVE_KEY_PATTERNS)


def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (_REDACTED if _is_sensitive_key(key) else value)
        for key, value in mapping.items()
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
            request["headers"] = _redact_mapping(headers)

        cookies = request.get("cookies")
        if isinstance(cookies, dict):
            request["cookies"] = _redact_mapping(cookies)

        query_string = request.get("query_string")
        if isinstance(query_string, dict):
            request["query_string"] = _redact_mapping(query_string)

        data = request.get("data")
        if isinstance(data, dict):
            request["data"] = _redact_mapping(data)

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _redact_mapping(extra)

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

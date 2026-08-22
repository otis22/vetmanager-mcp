"""Optional error tracking bootstrap for production runtimes."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.starlette import StarletteIntegration

SUPPORTED_ERROR_TRACKING_BACKENDS = {"sentry"}
_REDACTED = "[Filtered]"
_HANDLED_CONNECTION_FAILURE_TAG = "handled_connection_failure"
_MANUAL_TOOL_FAILURE_TAG = "mcp_tool_failure_capture"
_MANUAL_TOOL_FAILURE_VALUE = "manual"
_TOOL_ERROR_CAPTURE_MARKER = "_vetmanager_mcp_error_tracking_handled"
_configured = False

# Substrings matched case-insensitively against header/cookie/body keys.
# Any key containing one of these is replaced with _REDACTED.
_SENSITIVE_KEY_PATTERNS = (
    "token", "key", "secret", "auth", "api", "cookie", "bearer", "password",
    "credential", "session", "csrf",
    # Webhook/HMAC/JWT ecosystem (Stripe, GitHub, Slack webhooks etc.)
    "signature", "jwt", "hmac", "otp", "passphrase",
    # Stage 100.4: OAuth2 DPoP proof-of-possession + generic "signed" prefix
    "dpop", "signed",
    # Personal/request routing data. Clinic domain deliberately is not here:
    # owner approved it as incident-diagnostic metadata for stage 233.5.
    "client_ip", "x-forwarded-for", "x-real-ip", "remote_addr", "ip_address",
    "email", "phone", "login", "password",
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
    return lowered in {"name", "first_name", "last_name", "full_name"} or any(
        pattern in lowered for pattern in _SENSITIVE_KEY_PATTERNS
    )


def _redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (_REDACTED if _is_sensitive_key(key) else value)
        for key, value in mapping.items()
    }


def _resolve_release() -> str:
    configured_release = (os.environ.get("ERROR_TRACKING_RELEASE") or "").strip()
    if configured_release:
        return (
            configured_release
            if configured_release.startswith("vetmanager-mcp@")
            else f"vetmanager-mcp@{configured_release}"
        )
    try:
        package_version = version("vetmanager-mcp")
    except PackageNotFoundError:
        package_version = "unknown"
    return f"vetmanager-mcp@{package_version}"


def _exception_chain_contains_marker(exc: BaseException | None) -> bool:
    """Return whether an exception/cause/context chain was handled by MCP."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if getattr(exc, _TOOL_ERROR_CAPTURE_MARKER, False):
            return True
        exc = exc.__cause__
    return False


def _event_exception_is_marked(hint: dict[str, Any] | None) -> bool:
    if not isinstance(hint, dict):
        return False
    exc_info = hint.get("exc_info")
    if not isinstance(exc_info, tuple) or len(exc_info) < 2:
        return False
    exception = exc_info[1]
    return isinstance(exception, BaseException) and _exception_chain_contains_marker(exception)


def _is_private_handled_event(event: dict[str, Any]) -> bool:
    tags = event.get("tags")
    return isinstance(tags, dict) and (
        tags.get(_HANDLED_CONNECTION_FAILURE_TAG) == "true"
        or tags.get(_MANUAL_TOOL_FAILURE_TAG) == _MANUAL_TOOL_FAILURE_VALUE
    )


def _sanitize_event(event: dict[str, Any], hint: dict[str, Any] | None) -> dict[str, Any] | None:
    tags = event.get("tags")
    if (
        not (isinstance(tags, dict) and tags.get(_MANUAL_TOOL_FAILURE_TAG) == _MANUAL_TOOL_FAILURE_VALUE)
        and _event_exception_is_marked(hint)
    ):
        # The FastMCP boundary already emitted its safe manual event. Drop only
        # the automatic re-capture of that same marked exception chain.
        return None

    if _is_private_handled_event(event):
        # Starlette may attach the submitted form/request automatically. This
        # handled route event is diagnostic only; account_id + stack frames are
        # sufficient and avoid domains, emails, logins and credentials.
        request = event.get("request")
        request_data = request.get("data") if isinstance(request, dict) else None
        domain = request_data.get("domain") if isinstance(request_data, dict) else None
        if (
            isinstance(tags, dict)
            and tags.get(_HANDLED_CONNECTION_FAILURE_TAG) == "true"
            and isinstance(domain, str)
            and domain
        ):
            event.setdefault("tags", {})["clinic_domain"] = domain
        for key in ("request", "user", "contexts", "breadcrumbs", "extra"):
            event.pop(key, None)
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

        # Stage 100.1: WSGI/ASGI env often contains HTTP_AUTHORIZATION /
        # HTTP_COOKIE / HTTP_X_VM_API_KEY copies of headers.
        env = request.get("env")
        if isinstance(env, dict):
            request["env"] = _redact_mapping(env)

    extra = event.get("extra")
    if isinstance(extra, dict):
        event["extra"] = _redact_mapping(extra)

    # Stage 100.1: breadcrumbs[*].data often carry auth-flow payloads.
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
        if isinstance(values, list):
            for bc in values:
                if isinstance(bc, dict):
                    bc_data = bc.get("data")
                    if isinstance(bc_data, dict):
                        bc["data"] = _redact_mapping(bc_data)

    # Stage 100.1: exception.values[*].stacktrace.frames[*].vars — local
    # variables captured on exception often contain bearer tokens, passwords,
    # api keys assigned to local vars before the raise.
    exception = event.get("exception")
    if isinstance(exception, dict):
        exc_values = exception.get("values")
        if isinstance(exc_values, list):
            for exc_v in exc_values:
                if not isinstance(exc_v, dict):
                    continue
                if _is_private_handled_event(event):
                    exc_v["value"] = _REDACTED
                st = exc_v.get("stacktrace")
                if not isinstance(st, dict):
                    continue
                frames = st.get("frames")
                if not isinstance(frames, list):
                    continue
                for frame in frames:
                    if isinstance(frame, dict):
                        f_vars = frame.get("vars")
                        if isinstance(f_vars, dict):
                            frame["vars"] = (
                                {key: _REDACTED for key in f_vars}
                                if _is_private_handled_event(event)
                                else _redact_mapping(f_vars)
                            )

    # Stage 100.1: contexts and user scope carry runtime metadata.
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        for ctx_name, ctx_val in list(contexts.items()):
            if isinstance(ctx_val, dict):
                contexts[ctx_name] = _redact_mapping(ctx_val)

    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = _redact_mapping(user)

    tags = event.get("tags")
    if isinstance(tags, dict):
        event["tags"] = _redact_mapping(tags)

    return event


def configure_error_tracking() -> bool:
    """Initialize optional error tracking backend if runtime config is present."""
    global _configured
    dsn = (os.environ.get("ERROR_TRACKING_DSN") or os.environ.get("SENTRY_DSN") or "").strip()
    if not dsn:
        _configured = False
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
    _configured = True
    return True


def capture_handled_connection_failure(exc: BaseException, *, account_id: int) -> None:
    """Capture a safe handled connection failure without changing route behavior."""
    if not _configured or not sentry_sdk.is_initialized():
        return
    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_tag(_HANDLED_CONNECTION_FAILURE_TAG, "true")
            scope.set_tag("account_id", str(account_id))
            scope.clear_breadcrumbs()
            sentry_sdk.capture_exception(exc)
    except Exception:
        # Error tracking must never alter a user-visible handled failure.
        return


def mark_tool_error_as_handled(exc: BaseException) -> None:
    """Mark one terminal MCP error so automatic capture can drop its duplicate."""
    try:
        setattr(exc, _TOOL_ERROR_CAPTURE_MARKER, True)
    except Exception:
        # A marker is an optimisation for duplicate suppression only.
        return


def _upstream_status_from_exception(exc: BaseException) -> int | None:
    seen: set[int] = set()
    while id(exc) not in seen:
        seen.add(id(exc))
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int) and not isinstance(status_code, bool):
            return status_code
        next_exc = exc.__cause__
        if not isinstance(next_exc, BaseException):
            return None
        exc = next_exc
    return None


def capture_tool_failure(
    exc: BaseException,
    *,
    tool_name: str,
    account_id: int | None,
) -> None:
    """Capture one safe, semantic MCP tool failure without changing its result."""
    if not _configured or not sentry_sdk.is_initialized():
        return
    try:
        with sentry_sdk.push_scope() as scope:
            scope.set_tag(_MANUAL_TOOL_FAILURE_TAG, _MANUAL_TOOL_FAILURE_VALUE)
            scope.set_tag("tool", tool_name)
            if account_id is not None:
                scope.set_tag("account_id", str(account_id))
            upstream_status = _upstream_status_from_exception(exc)
            if upstream_status is not None:
                scope.set_tag("upstream_status", str(upstream_status))
            scope.set_transaction_name(tool_name)
            scope.clear_breadcrumbs()
            sentry_sdk.capture_exception(exc)
    except Exception:
        # Error tracking must never alter a tool failure seen by an MCP client.
        return

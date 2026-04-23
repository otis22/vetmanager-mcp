"""Shared helpers for token-centric auth audit events."""

from __future__ import annotations

import json
import re
from typing import Any

from fastmcp.server import dependencies as _fastmcp_dependencies
from sqlalchemy.ext.asyncio import AsyncSession

from observability_logging import AUDIT_LOGGER
from request_context import get_current_request_context
from storage_models import TokenUsageLog
from web_security import resolve_client_ip

TOKEN_EVENT_CREATED = "token_created"
TOKEN_EVENT_REVOKED = "token_revoked"
TOKEN_EVENT_EXPIRED = "token_expired"
TOKEN_EVENT_AUTH_SUCCEEDED = "token_auth_succeeded"
TOKEN_EVENT_AUTH_FAILED_REVOKED = "token_auth_failed_revoked"
TOKEN_EVENT_AUTH_FAILED_EXPIRED = "token_auth_failed_expired"
TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION = "token_auth_failed_no_connection"
TOKEN_EVENT_AUTH_FAILED_NO_SCOPES = "token_auth_failed_no_scopes"
TOKEN_EVENT_AUTH_FAILED_IP_DENIED = "token_auth_failed_ip_denied"
TOKEN_EVENT_AUTH_RATE_LIMITED = "token_auth_rate_limited"

_SENSITIVE_DETAIL_KEY_TOKENS = (
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
    "user_token",
)
_BEARER_TOKEN_PATTERN = re.compile(r"\bvm_st_[A-Za-z0-9_-]+\b")
_SAFE_DETAIL_KEYS = {"token_prefix"}


def _is_sensitive_detail_key(key: str) -> bool:
    normalized = key.strip().lower().replace("-", "_")
    if normalized in _SAFE_DETAIL_KEYS:
        return False
    return any(token in normalized for token in _SENSITIVE_DETAIL_KEY_TOKENS)


def _sanitize_detail_value(value: Any, *, key: str | None = None) -> Any:
    if key and _is_sensitive_detail_key(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(child_key): _sanitize_detail_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_detail_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_detail_value(item) for item in value]
    if isinstance(value, str):
        if key and key.strip().lower().replace("-", "_") in _SAFE_DETAIL_KEYS:
            return value
        return _BEARER_TOKEN_PATTERN.sub("[redacted]", value)
    return value


def _serialize_details(details: dict[str, Any]) -> str:
    """Serialize only safe audit metadata into stable JSON."""
    sanitized = {
        str(key): _sanitize_detail_value(value, key=str(key))
        for key, value in details.items()
    }
    return json.dumps(sanitized, ensure_ascii=True, sort_keys=True)


def get_request_audit_metadata() -> tuple[str | None, str | None]:
    """Return best-effort (ip_address, user_agent) for current HTTP request."""
    try:
        request = _fastmcp_dependencies.get_http_request()
    except Exception:
        return None, None

    headers = dict(request.headers)
    user_agent = (headers.get("user-agent") or "").strip() or None

    client = getattr(request, "client", None)
    ip_address = resolve_client_ip(
        client_host=getattr(client, "host", None),
        forwarded_for=headers.get("x-forwarded-for"),
    )
    if ip_address == "unknown":
        ip_address = None

    return ip_address, user_agent


def _get_request_correlation_metadata() -> dict[str, str]:
    context = get_current_request_context()
    return {
        key: value
        for key in ("request_id", "correlation_id")
        if (value := context.get(key))
    }


def add_token_usage_log(
    session: AsyncSession,
    *,
    bearer_token_id: int,
    event_type: str,
    details: dict[str, Any],
) -> TokenUsageLog:
    """Append a token-centric audit row with best-effort request metadata."""
    ip_address, user_agent = get_request_audit_metadata()
    enriched_details = {
        **details,
        **_get_request_correlation_metadata(),
    }
    audit_event = TokenUsageLog(
        bearer_token_id=bearer_token_id,
        event_type=event_type,
        ip_address=ip_address,
        user_agent=user_agent,
        details_json=_serialize_details(enriched_details),
    )
    session.add(audit_event)
    return audit_event


async def commit_token_usage_log(
    session: AsyncSession,
    audit_event: TokenUsageLog,
) -> None:
    """Commit staged token/audit changes, then log the committed audit event."""
    event_type = audit_event.event_type
    bearer_token_id = audit_event.bearer_token_id
    details = json.loads(audit_event.details_json or "{}")
    await session.commit()
    AUDIT_LOGGER.info(
        "Committed token audit event.",
        extra={
            "event_name": "token_audit_log_committed",
            "token_event_type": event_type,
            "bearer_token_id": bearer_token_id,
            "request_id": details.get("request_id"),
            "correlation_id": details.get("correlation_id"),
        },
    )

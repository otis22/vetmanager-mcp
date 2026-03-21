"""Shared helpers for token-centric auth audit events."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from storage_models import TokenUsageLog

TOKEN_EVENT_CREATED = "token_created"
TOKEN_EVENT_REVOKED = "token_revoked"
TOKEN_EVENT_EXPIRED = "token_expired"
TOKEN_EVENT_AUTH_SUCCEEDED = "token_auth_succeeded"
TOKEN_EVENT_AUTH_FAILED_REVOKED = "token_auth_failed_revoked"
TOKEN_EVENT_AUTH_FAILED_EXPIRED = "token_auth_failed_expired"
TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION = "token_auth_failed_no_connection"
TOKEN_EVENT_AUTH_RATE_LIMITED = "token_auth_rate_limited"


def _serialize_details(details: dict[str, Any]) -> str:
    """Serialize only safe audit metadata into stable JSON."""
    return json.dumps(details, ensure_ascii=True, sort_keys=True)


def get_request_audit_metadata() -> tuple[str | None, str | None]:
    """Return best-effort (ip_address, user_agent) for current HTTP request."""
    try:
        from fastmcp.server.dependencies import get_http_request

        request = get_http_request()
    except Exception:
        return None, None

    headers = dict(request.headers)
    user_agent = (headers.get("user-agent") or "").strip() or None

    forwarded_for = (headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        ip_address = forwarded_for.split(",", 1)[0].strip() or None
    else:
        client = getattr(request, "client", None)
        ip_address = getattr(client, "host", None)

    return ip_address, user_agent


def add_token_usage_log(
    session: AsyncSession,
    *,
    bearer_token_id: int,
    event_type: str,
    details: dict[str, Any],
) -> None:
    """Append a token-centric audit log entry with best-effort request metadata."""
    ip_address, user_agent = get_request_audit_metadata()
    session.add(
        TokenUsageLog(
            bearer_token_id=bearer_token_id,
            event_type=event_type,
            ip_address=ip_address,
            user_agent=user_agent,
            details_json=_serialize_details(details),
        )
    )

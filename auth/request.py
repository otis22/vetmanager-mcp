"""Extract bearer auth data from current HTTP request headers.

Stage 103a: extracted from `request_auth.py`.
Stage 109.5: `_get_request_headers` is now the canonical location here;
`request_credentials.py` keeps a shim re-export for legacy call sites.
New test monkey-patches should target `auth.request._get_request_headers`.
"""

from __future__ import annotations

from fastmcp.server import dependencies as _fastmcp_dependencies

from auth_audit import get_request_audit_metadata
from exceptions import AuthError
from observability_logging import SECURITY_LOGGER
from request_context import get_current_request_context
from service_metrics import record_auth_failure


def _get_request_headers() -> dict[str, str]:
    """Return current HTTP request headers, or empty dict outside HTTP context.

    Canonical location as of stage 109.5. `request_credentials._get_request_headers`
    re-exports this for backward compatibility.
    """
    try:
        request = _fastmcp_dependencies.get_http_request()
        return dict(request.headers)
    except Exception:
        return {}


def _log_bearer_header_failure(reason: str) -> None:
    client_ip, _ = get_request_audit_metadata()
    context = get_current_request_context()
    extra = {
        "event_name": "bearer_auth_failed",
        "source": "bearer_header",
        "reason": reason,
    }
    if client_ip is not None:
        extra["client_ip"] = client_ip
    for key in ("request_id", "correlation_id"):
        if value := context.get(key):
            extra[key] = value
    SECURITY_LOGGER.warning("Bearer authorization header rejected.", extra=extra)


def get_bearer_token() -> str:
    """Return bearer token from Authorization header."""
    headers = _get_request_headers()
    authorization = headers.get("authorization", "").strip()
    if not authorization:
        record_auth_failure(source="bearer_header", reason="missing_authorization")
        _log_bearer_header_failure("missing_authorization")
        raise AuthError(
            "Missing Authorization header. Set Authorization: Bearer <service_token>.",
            status_code=401,
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        record_auth_failure(source="bearer_header", reason="invalid_authorization")
        _log_bearer_header_failure("invalid_authorization")
        raise AuthError(
            "Invalid Authorization header. Use Authorization: Bearer <service_token>.",
            status_code=401,
        )
    return token.strip()

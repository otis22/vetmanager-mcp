"""Extract bearer auth data from current HTTP request headers.

Stage 103a: extracted from `request_auth.py`.
Stage 109.5: `_get_request_headers` is now the canonical location here;
`request_credentials.py` keeps a shim re-export for legacy call sites.
New test monkey-patches should target `auth.request._get_request_headers`.
"""

from __future__ import annotations

from exceptions import AuthError
from service_metrics import record_auth_failure


def _get_request_headers() -> dict[str, str]:
    """Return current HTTP request headers, or empty dict outside HTTP context.

    Canonical location as of stage 109.5. `request_credentials._get_request_headers`
    re-exports this for backward compatibility.
    """
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        return dict(request.headers)
    except Exception:
        return {}


def get_bearer_token() -> str:
    """Return bearer token from Authorization header."""
    headers = _get_request_headers()
    authorization = headers.get("authorization", "").strip()
    if not authorization:
        record_auth_failure(source="bearer_header", reason="missing_authorization")
        raise AuthError(
            "Missing Authorization header. Set Authorization: Bearer <service_token>.",
            status_code=401,
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        record_auth_failure(source="bearer_header", reason="invalid_authorization")
        raise AuthError(
            "Invalid Authorization header. Use Authorization: Bearer <service_token>.",
            status_code=401,
        )
    return token.strip()

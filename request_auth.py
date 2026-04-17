"""Extract bearer auth data from current HTTP request headers."""

from __future__ import annotations

from exceptions import AuthError
import request_credentials
from service_metrics import record_auth_failure


def get_bearer_token() -> str:
    """Return bearer token from Authorization header.

    Routes through `request_credentials._get_request_headers` (a re-export
    of the local `_get_request_headers`) so existing test monkeypatches
    targeting `request_credentials._get_request_headers` still intercept
    this call site.
    """
    headers = request_credentials._get_request_headers()
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

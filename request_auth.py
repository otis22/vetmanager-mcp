"""Extract bearer auth data from current HTTP request headers."""

from __future__ import annotations

from exceptions import AuthError
import request_credentials


def get_bearer_token() -> str:
    """Return bearer token from Authorization header."""
    headers = request_credentials._get_request_headers()
    authorization = headers.get("authorization", "").strip()
    if not authorization:
        raise AuthError(
            "Missing Authorization header. Set Authorization: Bearer <service_token>.",
            status_code=401,
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError(
            "Invalid Authorization header. Use Authorization: Bearer <service_token>.",
            status_code=401,
        )
    return token.strip()

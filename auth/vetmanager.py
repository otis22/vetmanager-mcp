"""Resolve a stored VetmanagerConnection into normalized credentials.

Stage 103a: extracted from `vetmanager_auth.py`. Thin resolver that
decrypts the connection payload and picks the right credential header
and value for the stored auth mode. Returns `VetmanagerAuthContext` from
`auth.context`.
"""

from __future__ import annotations

from auth.context import (
    DEFAULT_USER_TOKEN_APP_NAME,
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    VETMANAGER_USER_TOKEN_HEADER,
    VetmanagerAuthContext,
)
from exceptions import AuthError, VetmanagerError
from storage_models import VetmanagerConnection


def resolve_vetmanager_credentials(
    connection: VetmanagerConnection,
    *,
    encryption_key: str | None = None,
) -> VetmanagerAuthContext:
    """Resolve account connection into normalized Vetmanager credentials."""
    payload = connection.get_credentials(encryption_key=encryption_key) or {}

    domain = (payload.get("domain") or "").strip()
    if not domain:
        raise VetmanagerError("Account connection is missing Vetmanager domain.")

    if connection.auth_mode == VETMANAGER_AUTH_MODE_DOMAIN_API_KEY:
        api_key = (payload.get("api_key") or "").strip()
        if not api_key:
            raise AuthError(
                "Account connection is missing Vetmanager API key.",
                status_code=401,
            )
        return VetmanagerAuthContext(
            auth_mode=connection.auth_mode,
            domain=domain,
            credential=api_key,
        )

    if connection.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
        user_token = (payload.get("user_token") or "").strip()
        app_name = (payload.get("app_name") or DEFAULT_USER_TOKEN_APP_NAME).strip()
        if not user_token:
            raise AuthError(
                "Account connection is missing Vetmanager user token.",
                status_code=401,
            )
        return VetmanagerAuthContext(
            auth_mode=connection.auth_mode,
            domain=domain,
            credential=user_token,
            credential_header=VETMANAGER_USER_TOKEN_HEADER,
            app_name=app_name,
        )

    raise VetmanagerError(f"Unsupported Vetmanager auth mode: {connection.auth_mode}")

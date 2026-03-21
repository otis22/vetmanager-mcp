"""Vetmanager account connection auth modes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from exceptions import AuthError, VetmanagerError
from storage_models import VetmanagerConnection

VETMANAGER_AUTH_MODE_DOMAIN_API_KEY = "domain_api_key"
VETMANAGER_AUTH_MODE_USER_TOKEN = "user_token"
VETMANAGER_AUTH_HEADER = "X-REST-API-KEY"


@dataclass(slots=True)
class VetmanagerAuthContext:
    """Normalized Vetmanager auth context for runtime HTTP client usage."""

    auth_mode: str
    domain: str
    credential: str
    credential_header: str = VETMANAGER_AUTH_HEADER

    def build_headers(self) -> dict[str, str]:
        """Build outgoing Vetmanager API headers for this auth mode."""
        return {
            self.credential_header: self.credential,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @property
    def api_key(self) -> str:
        """Backward-compatible alias for runtime secret value."""
        return self.credential

    def credential_fingerprint(self) -> str:
        """Return short stable fingerprint for cache key isolation."""
        return hashlib.sha256(self.credential.encode("utf-8")).hexdigest()[:16]

    def api_key_fingerprint(self) -> str:
        """Backward-compatible alias for cache key isolation."""
        return self.credential_fingerprint()


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
        if not user_token:
            raise AuthError(
                "Account connection is missing Vetmanager user token.",
                status_code=401,
            )
        return VetmanagerAuthContext(
            auth_mode=connection.auth_mode,
            domain=domain,
            credential=user_token,
        )

    raise VetmanagerError(f"Unsupported Vetmanager auth mode: {connection.auth_mode}")

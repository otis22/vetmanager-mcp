"""Vetmanager account connection auth modes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from exceptions import AuthError, VetmanagerError
from storage_models import VetmanagerConnection

VETMANAGER_AUTH_MODE_DOMAIN_API_KEY = "domain_api_key"


@dataclass(slots=True)
class VetmanagerAuthContext:
    """Normalized Vetmanager auth context for runtime HTTP client usage."""

    auth_mode: str
    domain: str
    api_key: str

    def build_headers(self) -> dict[str, str]:
        """Build outgoing Vetmanager API headers for this auth mode."""
        return {
            "X-REST-API-KEY": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def api_key_fingerprint(self) -> str:
        """Return short stable fingerprint for cache key isolation."""
        return hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:16]


def resolve_vetmanager_credentials(
    connection: VetmanagerConnection,
    *,
    encryption_key: str | None = None,
) -> VetmanagerAuthContext:
    """Resolve account connection into normalized Vetmanager credentials."""
    payload = connection.get_credentials(encryption_key=encryption_key) or {}

    if connection.auth_mode != VETMANAGER_AUTH_MODE_DOMAIN_API_KEY:
        raise VetmanagerError(
            f"Unsupported Vetmanager auth mode: {connection.auth_mode}"
        )

    domain = (payload.get("domain") or "").strip()
    api_key = (payload.get("api_key") or "").strip()
    if not domain:
        raise VetmanagerError("Account connection is missing Vetmanager domain.")
    if not api_key:
        raise AuthError("Account connection is missing Vetmanager API key.", status_code=401)

    return VetmanagerAuthContext(
        auth_mode=connection.auth_mode,
        domain=domain,
        api_key=api_key,
    )

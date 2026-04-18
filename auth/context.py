"""Vetmanager auth-mode constants and normalized credential dataclass.

Stage 103a: extracted from `vetmanager_auth.py`. The dataclass here is a
pure data carrier — no DB lookup, no HTTP, no connection logic — so it
can be safely imported from any layer including low-level transports.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

VETMANAGER_AUTH_MODE_DOMAIN_API_KEY = "domain_api_key"
VETMANAGER_AUTH_MODE_USER_TOKEN = "user_token"
VETMANAGER_AUTH_HEADER = "X-REST-API-KEY"
VETMANAGER_USER_TOKEN_HEADER = "X-USER-TOKEN"
VETMANAGER_APP_NAME_HEADER = "X-APP-NAME"
DEFAULT_USER_TOKEN_APP_NAME = "vetmanager-mcp"


@dataclass(slots=True)
class VetmanagerAuthContext:
    """Normalized Vetmanager auth context for runtime HTTP client usage."""

    auth_mode: str
    domain: str
    credential: str
    credential_header: str = VETMANAGER_AUTH_HEADER
    app_name: str | None = None

    def build_headers(self) -> dict[str, str]:
        """Build outgoing Vetmanager API headers for this auth mode."""
        headers = {
            self.credential_header: self.credential,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.app_name:
            headers[VETMANAGER_APP_NAME_HEADER] = self.app_name
        return headers

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

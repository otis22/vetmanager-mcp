"""OAuth discovery metadata for ChatGPT-compatible MCP linking."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from token_scopes import SUPPORTED_TOKEN_SCOPES
from observability_logging import RUNTIME_LOGGER

DEFAULT_SITE_BASE_URL = "https://vetmanager-mcp.vromanichev.ru"
DEFAULT_MCP_PATH = "/mcp"
OAUTH_SCOPE_OFFLINE_ACCESS = "offline_access"


@dataclass(frozen=True, slots=True)
class PublicEndpointConfig:
    site_base_url: str
    mcp_path: str

    @property
    def mcp_resource_url(self) -> str:
        return f"{self.site_base_url}{self.mcp_path}"


def get_oauth_scopes_supported() -> list[str]:
    """Return OAuth discovery scopes: MCP tool scopes plus OAuth protocol scopes."""
    return [*SUPPORTED_TOKEN_SCOPES, OAUTH_SCOPE_OFFLINE_ACCESS]


def get_site_base_url() -> str:
    """Return canonical public site base URL without a trailing slash."""
    raw = (os.environ.get("SITE_BASE_URL") or DEFAULT_SITE_BASE_URL).strip()
    parsed = urlparse(raw)
    if (len(raw) > 255 or any(c in raw for c in ('"', "'", "<", ">", " ", "\t", "\n", "\r", "\x00"))
            or parsed.scheme not in {"http", "https"} or not parsed.netloc):
        return DEFAULT_SITE_BASE_URL
    return raw.rstrip("/")


def get_mcp_path() -> str:
    """Return normalized public MCP path."""
    raw = (os.environ.get("MCP_PATH") or DEFAULT_MCP_PATH).strip()
    if (len(raw) > 128 or any(c in raw for c in ('"', "'", "<", ">", " ", "\t", "\n", "\r", "\x00"))
            or not raw.startswith("/")):
        RUNTIME_LOGGER.warning("Invalid MCP_PATH; using default route.", extra={"event_name": "invalid_mcp_path"})
        return DEFAULT_MCP_PATH
    normalized = "/" + "/".join(part for part in raw.split("/") if part)
    return normalized or DEFAULT_MCP_PATH


def get_public_endpoint_config() -> PublicEndpointConfig:
    """Return the one validated public endpoint used by every public surface."""
    return PublicEndpointConfig(get_site_base_url(), get_mcp_path())


def get_mcp_resource_url() -> str:
    return get_public_endpoint_config().mcp_resource_url


def get_protected_resource_metadata_url() -> str:
    return f"{get_site_base_url()}/.well-known/oauth-protected-resource/mcp"


def build_protected_resource_metadata() -> dict:
    """Return RFC 9728-style protected resource metadata for the MCP resource."""
    base_url = get_site_base_url()
    return {
        "resource": get_mcp_resource_url(),
        "authorization_servers": [base_url],
        "scopes_supported": get_oauth_scopes_supported(),
        "resource_documentation": f"{base_url}/",
    }


def build_authorization_server_metadata() -> dict:
    """Return OAuth authorization server metadata for the public-client v1 flow."""
    base_url = get_site_base_url()
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "client_id_metadata_document_supported": False,
        "scopes_supported": get_oauth_scopes_supported(),
    }

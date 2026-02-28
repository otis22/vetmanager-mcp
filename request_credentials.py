"""Extract Vetmanager credentials from the current HTTP request headers.

Variant A: credentials come from the client's mcp.json `headers`:
  X-VM-Domain  — clinic subdomain
  X-VM-Api-Key — REST API key

Tools call `resolve_credentials(domain, api_key)` to merge explicit arguments
with request-level defaults from headers.
"""

import contextlib


def _get_request_headers() -> dict[str, str]:
    """Return current HTTP request headers or empty dict when not in HTTP context."""
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        return dict(request.headers)
    except Exception:
        return {}


def resolve_credentials(domain: str, api_key: str) -> tuple[str, str]:
    """Merge explicit tool arguments with request-header defaults.

    Priority (highest first):
      1. Explicit tool argument (non-empty string).
      2. X-VM-Domain / X-VM-Api-Key HTTP header from mcp.json.

    Returns (domain, api_key) — may still be empty strings if neither source
    provided the value; VetmanagerClient will raise an appropriate error.
    """
    headers = _get_request_headers()
    resolved_domain = (domain or "").strip() or headers.get("x-vm-domain", "").strip()
    resolved_api_key = (api_key or "").strip() or headers.get("x-vm-api-key", "").strip()
    return resolved_domain, resolved_api_key

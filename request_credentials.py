"""Extract Vetmanager credentials from current HTTP request headers."""


def _get_request_headers() -> dict[str, str]:
    """Return current HTTP request headers or empty dict when not in HTTP context."""
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        return dict(request.headers)
    except Exception:
        return {}


def get_request_credentials() -> tuple[str, str]:
    """Return (domain, api_key) from X-VM-* headers.

    Values are stripped and lower-case header names are supported by Starlette.
    """
    headers = _get_request_headers()
    domain = headers.get("x-vm-domain", "").strip()
    api_key = headers.get("x-vm-api-key", "").strip()
    return domain, api_key

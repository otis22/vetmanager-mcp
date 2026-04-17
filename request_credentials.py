"""Internal shim for reading current HTTP request headers.

Historical context: this module originally exposed `get_request_credentials()`
that read `X-VM-Domain` / `X-VM-Api-Key` headers. Stage 22.4 (bearer-only
runtime) removed that public contract — runtime credentials now come only
from `Authorization: Bearer <service_token>` resolved by `bearer_auth.py`.

What remains is the low-level `_get_request_headers()` helper used by
`request_auth.py` to introspect incoming headers. It is NOT a public API.
"""


def _get_request_headers() -> dict[str, str]:
    """Return current HTTP request headers, or empty dict outside HTTP context."""
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        return dict(request.headers)
    except Exception:
        return {}

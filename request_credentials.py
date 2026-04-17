"""Backward-compatibility shim for the header-reading helper.

Historical context: this module originally exposed `get_request_credentials()`
reading `X-VM-Domain` / `X-VM-Api-Key` headers. Stage 22.4 (bearer-only)
removed that public API; stage 92.2 deleted the function; stage 103.5
moved the remaining private helper `_get_request_headers()` to `request_auth`.

This shim preserves the old import path so tests that monkeypatch
`request_credentials._get_request_headers` keep working without a
mass-edit of 10+ test files.

New callers should import from `request_auth` directly.
"""

from __future__ import annotations


def _get_request_headers() -> dict[str, str]:
    """Return current HTTP request headers, or empty dict outside HTTP context."""
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        return dict(request.headers)
    except Exception:
        return {}

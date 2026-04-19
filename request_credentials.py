"""Backward-compatibility shim — canonical location is `auth.request`.

Historical context: this module originally exposed `get_request_credentials()`
reading `X-VM-Domain` / `X-VM-Api-Key` headers. Stage 22.4 (bearer-only)
removed that public API; stage 92.2 deleted the function.

Stage 109.5: `_get_request_headers` canonical location moved to
`auth/request.py`. This shim re-exports it for legacy imports + legacy
test monkey-patches that target `request_credentials._get_request_headers`.
New callers should import from `auth.request` directly.
"""

from __future__ import annotations

from auth.request import _get_request_headers  # noqa: F401

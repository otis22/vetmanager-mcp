"""Backward-compatibility shim — canonical location is `auth.request`.

Historical context: this module originally exposed `get_request_credentials()`
reading `X-VM-Domain` / `X-VM-Api-Key` headers. Stage 22.4 (bearer-only)
removed that public API; stage 92.2 deleted the function.

Stage 109.5: `_get_request_headers` canonical location moved to
`auth/request.py`. This shim re-exports it for legacy imports + legacy
test monkey-patches that target `request_credentials._get_request_headers`.
New callers MUST import from `auth.request` directly.

## Policy (stage 114b decision, 2026-04-19)

**KEEP** — explicit owner policy (option "keep all BC shims"):
- Stage 109.5 migrated 17 test-patch targets from `request_credentials`
  to `auth.request` (see AssumptionLog §109.5); grep shows 0 current
  patches against this path. Deletion is safe but deferred.
- 15 LOC cost; removal ROI low without a migration trigger.
- If re-visited: grep repo for `request_credentials._get_request_headers`
  / `patch.object(request_credentials, ...)` → confirm 0 matches → delete.
"""

from __future__ import annotations

from auth.request import _get_request_headers  # noqa: F401

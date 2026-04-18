"""Authentication package (stage 103a).

Consolidates five previously scattered top-level modules into one
namespace. Each submodule owns one concern:

- `auth.context`     — `VetmanagerAuthContext` dataclass + auth-mode constants.
- `auth.vetmanager`  — `resolve_vetmanager_credentials()` (connection → context).
- `auth.bearer`      — bearer-token lookup, `resolve_bearer_auth_context()`
                       pipeline, `_reject` helper.
- `auth.request`     — `get_bearer_token()` HTTP header parser.
- `auth.rate_limit`  — process-local bearer-token sliding-window rate limiter.

Top-level `bearer_auth.py`, `vetmanager_auth.py`, `request_auth.py`, and
`bearer_rate_limiter.py` remain as thin shims re-exporting from here so
existing imports and test monkey-patches keep working. New code should
import from `auth.<submodule>` directly.
"""

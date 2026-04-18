"""Backward-compat shim — canonical location is `auth.request`.

Stage 103a: bearer-token header parsing moved to `auth.request`. This
shim re-exports `get_bearer_token` so existing imports keep working.
"""

from auth.request import get_bearer_token  # noqa: F401

"""Backward-compat shim — canonical location is `auth.bearer`.

Stage 103a: the bearer-auth pipeline lives under `auth.bearer`. This
shim re-exports every public/underscore-prefixed name so existing
imports and test monkey-patches keep intercepting this module.
"""

from auth.bearer import (  # noqa: F401
    BearerAuthContext,
    _base_auth_details,
    _reject,
    resolve_bearer_auth_context,
)

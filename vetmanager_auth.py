"""Backward-compat shim — canonical location is `auth.context` / `auth.vetmanager`.

Stage 103a: `vetmanager_auth` moved under the `auth` package. This shim
re-exports the public surface so existing `from vetmanager_auth import
X` callers and test monkey-patches targeting `vetmanager_auth.X` keep
working. New code should import from `auth.context` (dataclass +
constants) or `auth.vetmanager` (resolver) directly.
"""

from auth.context import (  # noqa: F401
    DEFAULT_USER_TOKEN_APP_NAME,
    VETMANAGER_APP_NAME_HEADER,
    VETMANAGER_AUTH_HEADER,
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    VETMANAGER_USER_TOKEN_HEADER,
    VetmanagerAuthContext,
)
from auth.vetmanager import resolve_vetmanager_credentials  # noqa: F401

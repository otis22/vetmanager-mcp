"""Resolve runtime Vetmanager credentials from bearer auth context."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from bearer_auth import resolve_bearer_auth_context
from exceptions import AuthError, VetmanagerError
from request_auth import get_bearer_token
from storage import get_session_factory
from vetmanager_auth import VetmanagerAuthContext

DOMAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


@dataclass(slots=True)
class RuntimeCredentials:
    """Resolved Vetmanager credentials for one runtime request context."""

    vetmanager_auth: VetmanagerAuthContext
    source: str
    account_id: int | None = None
    bearer_token_id: int | None = None
    connection_id: int | None = None

    @property
    def domain(self) -> str:
        return self.vetmanager_auth.domain

    @property
    def api_key(self) -> str:
        return self.vetmanager_auth.api_key


def _validate_domain(domain: str) -> str:
    if not DOMAIN_PATTERN.fullmatch(domain):
        raise VetmanagerError(
            "Invalid Vetmanager domain format. Use clinic subdomain like 'myclinic'."
        )
    return domain


async def resolve_runtime_credentials() -> RuntimeCredentials:
    """Resolve runtime credentials strictly from bearer auth."""
    bearer_token = get_bearer_token()
    async with get_session_factory()() as session:
        context = await resolve_bearer_auth_context(
            bearer_token,
            session,
            encryption_key=os.environ.get("STORAGE_ENCRYPTION_KEY"),
        )
    return RuntimeCredentials(
        vetmanager_auth=VetmanagerAuthContext(
            auth_mode=context.auth_mode,
            domain=_validate_domain(context.domain),
            api_key=context.api_key,
        ),
        source="bearer",
        account_id=context.account_id,
        bearer_token_id=context.bearer_token_id,
        connection_id=context.connection_id,
    )

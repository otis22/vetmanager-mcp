"""Resolve runtime Vetmanager credentials from bearer auth context."""

from __future__ import annotations

import os
from dataclasses import dataclass

from bearer_auth import resolve_bearer_auth_context
from domain_validation import validate_domain as _validate_domain
from exceptions import AuthError, VetmanagerError
from request_auth import get_bearer_token
from secret_manager import get_storage_encryption_key
from storage import get_session_factory
from vetmanager_auth import VetmanagerAuthContext


@dataclass(slots=True)
class RuntimeCredentials:
    """Resolved Vetmanager credentials for one runtime request context."""

    vetmanager_auth: VetmanagerAuthContext
    source: str
    account_id: int | None = None
    bearer_token_id: int | None = None
    connection_id: int | None = None
    scopes: tuple[str, ...] = ()

    @property
    def domain(self) -> str:
        return self.vetmanager_auth.domain

    @property
    def api_key(self) -> str:
        return self.vetmanager_auth.api_key


async def resolve_runtime_credentials() -> RuntimeCredentials:
    """Resolve runtime credentials strictly from bearer auth."""
    bearer_token = get_bearer_token()
    async with get_session_factory()() as session:
        context = await resolve_bearer_auth_context(
            bearer_token,
            session,
            encryption_key=get_storage_encryption_key(),
        )
    return RuntimeCredentials(
        vetmanager_auth=VetmanagerAuthContext(
            auth_mode=context.vetmanager_auth.auth_mode,
            domain=_validate_domain(context.vetmanager_auth.domain),
            credential=context.vetmanager_auth.credential,
            credential_header=context.vetmanager_auth.credential_header,
            app_name=context.vetmanager_auth.app_name,
        ),
        source="bearer",
        account_id=context.account_id,
        bearer_token_id=context.bearer_token_id,
        connection_id=context.connection_id,
        scopes=context.scopes,
    )

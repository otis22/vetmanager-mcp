"""Resolve runtime Vetmanager credentials from bearer auth context."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone

from auth.vetmanager import resolve_vetmanager_credentials
from bearer_auth import resolve_bearer_auth_context
from bearer_token_manager import hash_bearer_token
from domain_validation import validate_domain as _validate_domain
from exceptions import AuthError, VetmanagerError
from oauth_metadata import get_mcp_resource_url
from oauth_challenge import oauth_challenge_details
from oauth_service import OAUTH_ACCESS_TOKEN_PREFIX, normalize_oauth_tool_scopes
from request_auth import get_bearer_token
from secret_manager import get_storage_encryption_key
from storage import get_session_factory
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    CONNECTION_STATUS_ACTIVE,
    OAUTH_STATUS_ACTIVE,
    Account,
    OAuthAccessToken,
    OAuthGrant,
    VetmanagerConnection,
)
from sqlalchemy import select
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
    is_depersonalized: bool = False
    auth_subject_type: str | None = None
    auth_subject_id: int | None = None

    @property
    def domain(self) -> str:
        return self.vetmanager_auth.domain

    @property
    def api_key(self) -> str:
        return self.vetmanager_auth.api_key


def _normalize_runtime_vetmanager_auth(context) -> VetmanagerAuthContext:
    return VetmanagerAuthContext(
        auth_mode=context.auth_mode,
        domain=_validate_domain(context.domain),
        credential=context.credential,
        credential_header=context.credential_header,
        app_name=context.app_name,
    )


def _invalid_oauth_token_error() -> AuthError:
    return AuthError(
        "Invalid authorization.",
        status_code=401,
        error_code="invalid_token",
        details=oauth_challenge_details(
            error="invalid_token",
            error_description="OAuth access token is invalid.",
        ),
    )


_CURRENT_RUNTIME_CREDENTIALS: ContextVar[RuntimeCredentials | None] = ContextVar(
    "current_runtime_credentials",
    default=None,
)


def get_current_runtime_credentials() -> RuntimeCredentials | None:
    """Return request-local resolved credentials, if a tool wrapper set them."""
    return _CURRENT_RUNTIME_CREDENTIALS.get()


@contextmanager
def use_runtime_credentials(credentials: RuntimeCredentials):
    """Expose resolved credentials within one MCP tool call and reset reliably."""
    token = _CURRENT_RUNTIME_CREDENTIALS.set(credentials)
    try:
        yield
    finally:
        _CURRENT_RUNTIME_CREDENTIALS.reset(token)


async def resolve_runtime_credentials() -> RuntimeCredentials:
    """Resolve runtime credentials strictly from bearer auth."""
    cached = get_current_runtime_credentials()
    if cached is not None:
        return cached

    bearer_token = get_bearer_token()
    if bearer_token.startswith(OAUTH_ACCESS_TOKEN_PREFIX):
        return await _resolve_oauth_runtime_credentials(bearer_token)

    async with get_session_factory()() as session:
        context = await resolve_bearer_auth_context(
            bearer_token,
            session,
            encryption_key=get_storage_encryption_key(),
        )
    return RuntimeCredentials(
        vetmanager_auth=_normalize_runtime_vetmanager_auth(context.vetmanager_auth),
        source="bearer",
        account_id=context.account_id,
        bearer_token_id=context.bearer_token_id,
        connection_id=context.connection_id,
        scopes=context.scopes,
        is_depersonalized=context.is_depersonalized,
        auth_subject_type="service_bearer",
        auth_subject_id=context.bearer_token_id,
    )


async def _resolve_oauth_runtime_credentials(raw_token: str) -> RuntimeCredentials:
    now = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        access_token = await session.scalar(
            select(OAuthAccessToken).where(OAuthAccessToken.token_hash == hash_bearer_token(raw_token))
        )
        if access_token is None:
            raise _invalid_oauth_token_error()
        expires_at = access_token.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if (
            access_token.status != OAUTH_STATUS_ACTIVE
            or expires_at <= now
            or access_token.resource != get_mcp_resource_url()
        ):
            raise _invalid_oauth_token_error()

        grant = await session.get(OAuthGrant, access_token.grant_id)
        if grant is None or grant.status != OAUTH_STATUS_ACTIVE:
            raise _invalid_oauth_token_error()
        account = await session.get(Account, grant.account_id)
        if account is None or account.status != ACCOUNT_STATUS_ACTIVE:
            raise _invalid_oauth_token_error()
        connection = await session.get(VetmanagerConnection, grant.vetmanager_connection_id)
        if connection is None or connection.status != CONNECTION_STATUS_ACTIVE:
            raise _invalid_oauth_token_error()

        resolved = resolve_vetmanager_credentials(
            connection,
            encryption_key=get_storage_encryption_key(),
        )
        access_token_id = access_token.id
        account_id = grant.account_id
        connection_id = grant.vetmanager_connection_id
        scopes = tuple(normalize_oauth_tool_scopes(access_token.scope.split()))
        is_depersonalized = True if grant.is_depersonalized is not False else False
        access_token.last_used_at = now
        grant.last_used_at = now
        await session.commit()

    return RuntimeCredentials(
        vetmanager_auth=_normalize_runtime_vetmanager_auth(resolved),
        source="oauth",
        account_id=account_id,
        bearer_token_id=None,
        connection_id=connection_id,
        scopes=scopes,
        is_depersonalized=is_depersonalized,
        auth_subject_type="oauth_access_token",
        auth_subject_id=access_token_id,
    )

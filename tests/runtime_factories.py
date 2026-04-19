"""Shared test factories for bearer runtime and Vetmanager client helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import auth.request as auth_request
import runtime_auth
from token_scopes import SUPPORTED_TOKEN_SCOPES
from vetmanager_auth import VETMANAGER_AUTH_MODE_DOMAIN_API_KEY, VetmanagerAuthContext
from vetmanager_client import VetmanagerClient


def make_vetmanager_auth_context(
    domain: str,
    credential: str,
    *,
    auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
) -> VetmanagerAuthContext:
    """Build normalized Vetmanager auth context for runtime tests.

    Stage 109.1: automatically fills `credential_header` + `app_name`
    for `user_token` mode so callers don't have to hand-build these
    overrides at each test site (previously inlined in test_e2e_real).
    """
    from auth.context import (
        DEFAULT_USER_TOKEN_APP_NAME,
        VETMANAGER_AUTH_HEADER,
        VETMANAGER_AUTH_MODE_USER_TOKEN,
        VETMANAGER_USER_TOKEN_HEADER,
    )
    if auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
        return VetmanagerAuthContext(
            auth_mode=auth_mode,
            domain=domain,
            credential=credential,
            credential_header=VETMANAGER_USER_TOKEN_HEADER,
            app_name=DEFAULT_USER_TOKEN_APP_NAME,
        )
    return VetmanagerAuthContext(
        auth_mode=auth_mode,
        domain=domain,
        credential=credential,
        credential_header=VETMANAGER_AUTH_HEADER,
    )


def make_runtime_credentials(
    domain: str,
    credential: str,
    *,
    auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    account_id: int = 1,
    bearer_token_id: int = 1,
    connection_id: int = 1,
    scopes: tuple[str, ...] = SUPPORTED_TOKEN_SCOPES,
) -> runtime_auth.RuntimeCredentials:
    """Build normalized runtime credentials for bearer-auth tests."""
    return runtime_auth.RuntimeCredentials(
        vetmanager_auth=make_vetmanager_auth_context(
            domain,
            credential,
            auth_mode=auth_mode,
        ),
        source="bearer",
        account_id=account_id,
        bearer_token_id=bearer_token_id,
        connection_id=connection_id,
        scopes=tuple(scopes),
    )


def make_client_with_resolved_runtime(
    domain: str,
    credential: str,
    *,
    auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    bearer_token: str = "test-token",
    account_id: int = 1,
    bearer_token_id: int = 1,
    connection_id: int = 1,
    scopes: tuple[str, ...] = SUPPORTED_TOKEN_SCOPES,
) -> VetmanagerClient:
    """Build a client with resolved runtime auth state, bypassing DB lookup.

    **Stage 109.1 invariant**: this is the ONLY place that directly mutates
    VetmanagerClient private attributes. If those names ever get renamed
    (e.g. `_domain` → `_vm_domain`), update the block below and callers
    of this factory keep working unchanged.

    Tests that read private attributes for inspection (`client._domain` in
    asserts) are OK — renaming surfaces those as loud failures immediately,
    unlike silent drift in a writer copy.
    """
    headers = {"authorization": f"Bearer {bearer_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        client = VetmanagerClient()
    auth_context = make_vetmanager_auth_context(domain, credential, auth_mode=auth_mode)
    client._vetmanager_auth = auth_context
    client._auth_source = "bearer"
    client._domain = domain
    client._api_key = credential
    client._account_id = account_id
    client._bearer_token_id = bearer_token_id
    client._connection_id = connection_id
    client._scopes = tuple(scopes)
    client._credentials_lock = asyncio.Lock()
    client._ensure_runtime_credentials = AsyncMock(return_value=None)
    return client


def patch_runtime_credentials(
    domain: str,
    credential: str,
    *,
    auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    bearer_token: str = "integration-token",
    account_id: int = 1,
    bearer_token_id: int = 11,
    connection_id: int = 21,
    scopes: tuple[str, ...] = SUPPORTED_TOKEN_SCOPES,
) -> tuple:
    """Return patches for bearer header extraction and runtime credential resolve."""
    headers_patch = patch.object(
        auth_request,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {bearer_token}"},
    )
    runtime_patch = patch(
        "vetmanager_client.resolve_runtime_credentials",
        AsyncMock(
            return_value=make_runtime_credentials(
                domain,
                credential,
                auth_mode=auth_mode,
                account_id=account_id,
                bearer_token_id=bearer_token_id,
                connection_id=connection_id,
                scopes=scopes,
            )
        ),
    )
    return headers_patch, runtime_patch

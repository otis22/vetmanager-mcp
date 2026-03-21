"""Shared test factories for bearer runtime and Vetmanager client helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import request_credentials
import runtime_auth
from vetmanager_auth import VETMANAGER_AUTH_MODE_DOMAIN_API_KEY, VetmanagerAuthContext
from vetmanager_client import VetmanagerClient


def make_vetmanager_auth_context(
    domain: str,
    credential: str,
    *,
    auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
) -> VetmanagerAuthContext:
    """Build normalized Vetmanager auth context for runtime tests."""
    return VetmanagerAuthContext(
        auth_mode=auth_mode,
        domain=domain,
        credential=credential,
    )


def make_runtime_credentials(
    domain: str,
    credential: str,
    *,
    auth_mode: str = VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    account_id: int = 1,
    bearer_token_id: int = 1,
    connection_id: int = 1,
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
) -> VetmanagerClient:
    """Build a client with resolved runtime auth state, bypassing DB lookup."""
    headers = {"authorization": f"Bearer {bearer_token}"}
    with patch.object(request_credentials, "_get_request_headers", return_value=headers):
        client = VetmanagerClient()
    auth_context = make_vetmanager_auth_context(domain, credential, auth_mode=auth_mode)
    client._vetmanager_auth = auth_context
    client._auth_source = "bearer"
    client._domain = domain
    client._api_key = credential
    client._account_id = account_id
    client._bearer_token_id = bearer_token_id
    client._connection_id = connection_id
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
) -> tuple:
    """Return patches for bearer header extraction and runtime credential resolve."""
    headers_patch = patch.object(
        request_credentials,
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
            )
        ),
    )
    return headers_patch, runtime_patch

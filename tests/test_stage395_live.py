"""Opt-in live read/write verification for identifier aliases; prints no clinic data."""

import json
import os
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="Requires the .env TEST_DOMAIN/TEST_API_KEY contour")
async def test_stage395_live_alias_and_canonical_read_plus_idempotent_write(capsys):
    original_request = httpx.AsyncClient.request
    observed = []

    async def capture(client, method, url, **kwargs):
        response = await original_request(client, method, url, **kwargs)
        if "/rest/api/pet" in str(url):
            observed.append((method, response.status_code))
            if method == "PUT":
                assert "owner_id" in (kwargs.get("json") or {})
        return response

    headers, runtime = patch_runtime_credentials(os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"])
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        seed = (await mcp.call_tool("get_pets", {"limit": 1})).structured_content
        pet = seed["data"]["pet"][0]
        pet_id, client_id = pet["id"], pet["client_id"]
        canonical = await mcp.call_tool("get_pets", {"client_id": client_id, "limit": 1})
        legacy = await mcp.call_tool("get_pets", {"owner_id": client_id, "limit": 2})
        written = await mcp.call_tool("update_pet", {"pet_id": pet_id, "client_id": client_id})
    safe_body = {"canonical": bool(canonical.structured_content.get("success")),
                 "alias": bool(legacy.structured_content.get("success")),
                 "write": bool(written.structured_content.get("success"))}
    with capsys.disabled():
        print(f"stage395 live HTTP codes={observed} body={json.dumps(safe_body)}")
    assert safe_body == {"canonical": True, "alias": True, "write": True}
    assert any(method == "GET" and code == 200 for method, code in observed)
    assert any(method == "PUT" and code in {200, 201} for method, code in observed)

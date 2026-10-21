"""Opt-in read-only profile proof on the .env API-key contour."""

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
                    reason=".env test contour credentials absent")
async def test_stage428_live_client_profile_read_only(capsys):
    original_request = httpx.AsyncClient.request
    observed = []

    async def capture(client, method, url, **kwargs):
        response = await original_request(client, method, url, **kwargs)
        if "/rest/api/admission" in str(url):
            observed.append((method, response.status_code))
        return response

    headers, runtime = patch_runtime_credentials(os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"])
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        clients = (await mcp.call_tool("get_clients", {"limit": 1})).structured_content
        client_id = clients["data"]["client"][0]["id"]
        profile = await mcp.call_tool("get_client_profile", {"client_id": client_id})

    body = profile.structured_content or {}
    safe_body = {
        "client_present": bool(body.get("client")),
        "next_admission_present": body.get("next_admission") is not None,
        "partial": bool(body.get("partial")),
    }
    with capsys.disabled():
        print(f"STAGE428_PROFILE codes={observed} body={json.dumps(safe_body)}")
    assert not profile.is_error
    assert safe_body["client_present"]
    assert not safe_body["partial"]
    assert observed == [("GET", 200), ("GET", 200)]

"""Read-only live privacy proof with two real bearer modes on the .env contour."""

import json
import os
import re

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync
from tests.test_stage389_live import _rpc


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="test API credentials absent")
def test_stage410_pet_list_privacy_live(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=90) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage410-live@example.test", "password": "Stage410-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200

        tokens = {}
        for depersonalized in (False, True):
            issued = _post_with_csrf_sync(client, "/account/tokens", data={
                "token_name": "Stage 410 privacy read", "expires_in_days": "1",
                "ip_mask": "*.*.*.*", "access_preset": "read_only",
                "is_depersonalized": "1" if depersonalized else "0",
            }, page_path="/account")
            assert issued.status_code == 200
            match = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
            assert match is not None
            tokens[depersonalized] = match.group(0)

        def activate(depersonalized):
            client.headers.pop("Mcp-Session-Id", None)
            client.headers.update({
                "Authorization": f"Bearer {tokens[depersonalized]}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json", "MCP-Protocol-Version": "2025-03-26",
            })
            initialized = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "stage410-live", "version": "1"},
                },
            })
            assert initialized.status_code == 200
            client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
            ready = client.post("/mcp", json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            assert ready.status_code in (200, 202)

        request_id = 2

        def invoke(tool, arguments):
            nonlocal request_id
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            })
            request_id += 1
            assert response.status_code == 200
            result = _rpc(response)["result"]
            assert result.get("isError") is False, tool
            body = result.get("structuredContent") or json.loads(result["content"][0]["text"])
            return response.status_code, body

        def rows(tool, body):
            if tool == "get_inactive_pets":
                return body["inactive_pets"]
            if tool == "get_pets":
                return body["data"]["pet"]
            return body["data"]["pets"]

        def contact(tool, row):
            if tool == "get_inactive_pets":
                return row.get("owner_phone")
            owner = row.get("owner")
            if not isinstance(owner, dict):
                return None
            if tool == "find_pets_by_alias":
                return owner.get("phone")
            return owner.get("cell_phone") or owner.get("home_phone")

        activate(False)
        inactive_args = {"months_min": 1, "months_max": 240, "limit": 20}
        _, inactive_seed = invoke("get_inactive_pets", inactive_args)
        inactive_row = next((row for row in rows("get_inactive_pets", inactive_seed)
                             if contact("get_inactive_pets", row)), None)
        assert inactive_row is not None, "test contour needs an inactive pet with owner phone"
        pet_args = {"client_id": inactive_row["client_id"], "limit": 100}
        _, pet_seed = invoke("get_pets", pet_args)
        pet_row = next((row for row in rows("get_pets", pet_seed)
                        if row["id"] == inactive_row["id"] and contact("get_pets", row)), None)
        assert pet_row is not None, "test contour needs embedded owner contact"
        alias_args = {"alias": pet_row["alias"], "limit": 100}
        _, alias_seed = invoke("find_pets_by_alias", alias_args)
        alias_row = next((row for row in rows("find_pets_by_alias", alias_seed)
                          if row["id"] == pet_row["id"] and contact("find_pets_by_alias", row)), None)
        assert alias_row is not None, "test contour needs alias owner contact"

        cases = (
            ("get_inactive_pets", inactive_args, inactive_row),
            ("get_pets", pet_args, pet_row),
            ("find_pets_by_alias", alias_args, alias_row),
        )
        for depersonalized in (False, True):
            if depersonalized:
                activate(True)
            for tool, args, source in cases:
                original = contact(tool, source)
                assert isinstance(original, str) and original
                for masked in (False, True):
                    code, body = invoke(tool, {**args, "mask_contacts": masked})
                    row = next((item for item in rows(tool, body) if item["id"] == source["id"]), None)
                    assert row is not None and row["id"] == source["id"]
                    actual = contact(tool, row)
                    if masked:
                        assert actual == "[redacted-phone]"
                    elif depersonalized:
                        assert actual != original
                    else:
                        assert actual == original
                    if tool == "get_inactive_pets" and row.get("doctor_id"):
                        assert row["doctor_name"] == f"[user:{row['doctor_id']}:first_name]"
                    print("STAGE410_LIVE", tool, "no_pd" if depersonalized else "pd",
                          "mask_on" if masked else "mask_off", code,
                          json.dumps({"row_count": len(rows(tool, body)),
                                      "same_id": True, "source_contact_present": True,
                                      "contact_masked": actual != original,
                                      "marker": actual if masked else None},
                                     sort_keys=True))

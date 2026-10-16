"""Read-only projection proof on the opt-in .env test API contour."""

import json
import os
import re

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync
from tests.test_stage388_live import _rpc


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="test API credentials absent")
def test_stage399_projection_live(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage399-live@example.test", "password": "Stage399-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 399 projection read", "expires_in_days": "1",
            "ip_mask": "*.*.*.*", "access_preset": "full_access",
            "confirm_full_access": "1",
        }, page_path="/account")
        assert issued.status_code == 200
        match = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
        assert match is not None
        client.headers.update({
            "Authorization": f"Bearer {match.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json", "MCP-Protocol-Version": "2025-03-26",
        })
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage399-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
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
            assert not result.get("isError"), f"{tool} returned an error"
            payload = result.get("structuredContent") or json.loads(result["content"][0]["text"])
            assert payload.get("success") is True
            return response.status_code, payload

        admission_day = None
        nested_contact_verified = False
        owner_contact_verified = False
        for tool, entity in (("get_admissions", "admission"),
                             ("get_invoices", "invoice"), ("get_clients", "client")):
            sizes = {}
            full_nested = None
            full_owner = None
            full_row_id = None
            for mode, arguments in (("full", {"limit": 1}),
                                    ("fields", {"limit": 1, "fields": ["id", "status"]}),
                                    ("compact", {"limit": 1, "compact": True}),
                                    ("include_empty", {"limit": 1, "include": []}),
                                    ("include_one", {"limit": 1, "compact": True,
                                                     "include": [{"get_admissions": "client",
                                                                  "get_invoices": "doctor",
                                                                  "get_clients": "city_data"}[tool]]}),
                                    ("masked", {"limit": 1, "mask_contacts": True})):
                status_code, payload = invoke(tool, arguments)
                if mode == "full":
                    print("STAGE399_RESPONSE_KEYS", tool, sorted(payload))
                data = payload["data"]
                rows = data if isinstance(data, list) else data[entity]
                assert rows and isinstance(rows[0], dict), f"{tool}/{mode} needs a nonempty list"
                if mode == "full":
                    full_row_id = rows[0]["id"]
                    print("STAGE399_NESTED_KEYS", tool, sorted(
                        key for key, value in rows[0].items() if isinstance(value, (dict, list))
                    ))
                if tool == "get_admissions" and mode == "full":
                    admission_day = rows[0]["admission_date"][:10]
                if mode == "full" and tool in {"get_admissions", "get_invoices"}:
                    full_nested = rows[0].get("client")
                    pet = rows[0].get("pet")
                    full_owner = pet.get("owner") if isinstance(pet, dict) else None
                if mode == "masked" and isinstance(full_nested, dict):
                    assert rows[0]["id"] == full_row_id
                    masked_nested = rows[0].get("client")
                    if isinstance(masked_nested, dict):
                        for contact_key in ("cell_phone", "home_phone", "work_phone", "email", "address"):
                            original = full_nested.get(contact_key)
                            if isinstance(original, str) and original:
                                assert masked_nested.get(contact_key) != original
                                nested_contact_verified = True
                if mode == "masked" and isinstance(full_owner, dict):
                    assert rows[0]["id"] == full_row_id
                    pet = rows[0].get("pet")
                    masked_owner = pet.get("owner") if isinstance(pet, dict) else None
                    assert isinstance(masked_owner, dict)
                    for contact_key in ("cell_phone", "home_phone", "work_phone", "email", "address"):
                        original = full_owner.get(contact_key)
                        if isinstance(original, str) and original:
                            assert masked_owner.get(contact_key) != original
                            owner_contact_verified = True
                if mode == "fields":
                    assert set(rows[0]) == {"id", "status"}
                if mode == "include_empty":
                    assert not ({"client", "pet", "invoices", "d", "doctor", "invoiceDocuments",
                                 "city_data", "street_data", "pets"} & rows[0].keys())
                if mode == "include_one":
                    relation = {"get_admissions": "client", "get_invoices": "doctor",
                                "get_clients": "city_data"}[tool]
                    assert relation in rows[0]
                encoded_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
                sizes[mode] = encoded_bytes
                safe_body = {
                    "success": True, "row_count": len(rows),
                    "total_present": isinstance(data, dict) and "totalCount" in data,
                    "row_key_count": len(rows[0]), "bytes": encoded_bytes,
                }
                print("STAGE399_LIVE", tool, mode, status_code,
                      json.dumps(safe_body, sort_keys=True))
            assert sizes["compact"] < sizes["full"], tool
        assert nested_contact_verified, "test contour needs one nested client contact"
        print("STAGE399_NESTED_CONTACT_MASK", 200,
              json.dumps({"contact_present": True, "contact_values_masked": True,
                          "owner_contact_verified": owner_contact_verified}))

        # Pick a real row with a nonempty contact; compare in memory only.
        _, clients = invoke("get_clients", {"limit": 100})
        client_rows = clients["data"]["client"]
        contact_keys = ("cell_phone", "home_phone", "work_phone", "email", "address")
        chosen = next((row for row in client_rows
                       if any(isinstance(row.get(key), str) and row[key] for key in contact_keys)), None)
        assert chosen is not None, "test contour needs one contact-bearing client"
        _, masked = invoke("get_clients", {"limit": 1, "mask_contacts": True,
                                            "filter": [{"property": "id", "operator": "=",
                                                        "value": chosen["id"]}]})
        masked_row = masked["data"]["client"][0]
        assert masked_row["id"] == chosen["id"]
        for key in contact_keys:
            if chosen.get(key):
                assert masked_row[key] != chosen[key]
        print("STAGE399_CONTACT_MASK", 200, json.dumps({
            "success": True, "contact_present": True, "contact_values_masked": True,
            "row_count": 1, "bytes": len(json.dumps(masked).encode()),
        }, sort_keys=True))

        assert admission_day is not None
        status_code, summary = invoke("get_admissions_daily_summary", {"date": admission_day})
        assert summary["processed_count"] > 0
        assert set(summary) == {"success", "date", "processed_count", "total_count",
                                "status_counts", "truncated", "complete"}
        assert sum(summary["status_counts"].values()) == summary["processed_count"]
        print("STAGE399_DAILY_SUMMARY", status_code, json.dumps({
            "success": True, "processed_count": summary["processed_count"],
            "total_present": summary["total_count"] is not None,
            "status_bucket_count": len(summary["status_counts"]),
            "complete": summary["complete"], "truncated": summary["truncated"],
            "bytes": len(json.dumps(summary).encode()),
        }, sort_keys=True))

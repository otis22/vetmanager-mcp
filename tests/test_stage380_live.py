"""Opt-in HTTP MCP proof of staff filters on isolated devtr6 storage."""

import json
import os

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer


pytestmark = pytest.mark.real_api


def _rpc(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: "))
    return response.json()


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
def test_stage380_live_staff_filters(live_server_url, prepared_web_db, upstream_mock_router):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    upstream_mock_router.get("https://billing-api.vetmanager.cloud/host/devtr6").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://devtr6.vetmanager.cloud"}})
    )
    cards = [
        {"id": 1, "doctor_id": 7, "creator_id": 8},
        {"id": 2, "doctor_id": 7, "creator_id": 9},
        {"id": 3, "doctor_id": 6, "creator_id": 8},
    ]
    queries = []

    def upstream(request):
        filters = json.loads(request.url.params["filter"])
        queries.append(filters)
        selected = cards
        for key in ("doctor_id", "creator_id"):
            clause = [item for item in filters if item["property"] == key]
            assert len(clause) <= 1
            if clause:
                assert clause[0]["operator"] == "="
                selected = [card for card in selected if card[key] == int(clause[0]["value"])]
        return httpx.Response(200, json={"success": True, "data": {
            "totalCount": len(selected), "medicalCards": selected,
        }})

    upstream_mock_router.get("https://devtr6.vetmanager.cloud/rest/api/MedicalCards").mock(
        side_effect=upstream)
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=30) as client:
        def call(method, params, number):
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": number, "method": method, "params": params,
            })
            assert response.status_code == 200
            body = _rpc(response)
            assert "error" not in body
            return body["result"]

        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage380-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)
        listed = call("tools/list", {}, 2)["tools"]
        tools = {tool["name"]: tool for tool in listed}
        assert {"doctor_id", "creator_id"} <= tools["get_medical_cards_by_date"]["inputSchema"]["properties"].keys()
        assert "doctor_id" in tools["get_medical_cards_by_date"]["description"]
        assert "creator_id" in tools["get_medical_cards_by_date"]["description"]
        assert "pet_id" in tools["get_medical_cards"]["description"]

        def cards_for(staff, number):
            result = call("tools/call", {"name": "get_medical_cards_by_date", "arguments": {
                "date": "2026-07-01", "limit": 20, **staff,
            }}, number)
            assert result.get("isError") is not True, result.get("content")
            return result["structuredContent"]

        zero = cards_for({"doctor_id": 0, "creator_id": -1}, 3)
        unfiltered = cards_for({}, 4)
        doctor = cards_for({"doctor_id": 7}, 5)
        creator = cards_for({"creator_id": 8}, 6)
        both = cards_for({"doctor_id": 7, "creator_id": 8}, 7)

    assert [card["id"] for card in unfiltered["medical_cards"]] == [1, 2, 3]
    assert [card["id"] for card in doctor["medical_cards"]] == [1, 2]
    assert [card["id"] for card in creator["medical_cards"]] == [1, 3]
    assert [card["id"] for card in both["medical_cards"]] == [1]
    assert [card["id"] for card in zero["medical_cards"]] == [1, 2, 3]
    assert [(x["total"], x["truncated"]) for x in (unfiltered, doctor, creator, both, zero)] == [
        (3, False), (2, False), (2, False), (1, False), (3, False),
    ]
    assert [
        [(f["property"], f["value"]) for f in query if f["property"] in ("doctor_id", "creator_id")]
        for query in queries
    ] == [[], [("doctor_id", "7")], [("creator_id", "8")],
          [("doctor_id", "7"), ("creator_id", "8")]]
    def clean_body(body):
        return {"ids": [card["id"] for card in body["medical_cards"]],
                "total": body["total"], "truncated": body["truncated"]}

    print("STAGE380_LIVE", json.dumps({
        "http": 200, "mcp": "success", "tools_list": [
            {"name": name, "description": tools[name]["description"],
             "staff_schema": {key: tools[name]["inputSchema"]["properties"].get(key)
                              for key in ("doctor_id", "creator_id")}}
            for name in ("get_medical_cards", "get_medical_cards_by_date")],
        "unfiltered": clean_body(unfiltered),
        "doctor": clean_body(doctor),
        "creator": clean_body(creator),
        "both": clean_body(both),
        "zero": clean_body(zero),
        "staff_queries": [
            [f for f in query if f["property"] in ("doctor_id", "creator_id")]
            for query in queries
        ],
    }, ensure_ascii=False))

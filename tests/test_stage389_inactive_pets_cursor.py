"""Stage 389 guard: a composite pet walk resumes without losing an owner."""

import json
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

BASE = "https://testclinic.vetmanager.cloud"


def _client(cid):
    return {"id": cid, "last_visit_date": "2024-12-15 14:30:00",
            "last_name": "Owner", "first_name": "Test", "cell_phone": ""}


def _mock_data(clients, pet_ids_by_client, *, total=None):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}}))

    def client_page(request):
        query = parse_qs(request.url.query.decode())
        offset = int(query.get("offset", [0])[0])
        size = int(query.get("limit", [100])[0])
        page = clients[offset:offset + size]
        data = {"client": page}
        if total is not None:
            data["totalCount"] = total
        return httpx.Response(200, json={"data": data})

    route = respx.get(f"{BASE}/rest/api/client").mock(side_effect=client_page)
    pets = [{"id": pid, "owner_id": cid, "status": "alive", "alias": "P"}
            for cid, ids in pet_ids_by_client.items() for pid in ids]
    invoices = [{"id": 1000 + p["id"], "pet_id": p["id"],
                 "invoice_date": "2024-12-15 15:00:00"} for p in pets]
    def pet_page(request):
        query = parse_qs(request.url.query.decode())
        clauses = json.loads(query["filter"][0])
        min_id = next((int(c["value"]) for c in clauses
                       if c["property"] == "id" and c["operator"] == ">"), 0)
        selected = [pet for pet in pets if pet["id"] > min_id]
        return httpx.Response(200, json={"data": {
            "pet": selected, "totalCount": len(selected),
        }})

    respx.get(f"{BASE}/rest/api/pet").mock(side_effect=pet_page)
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=httpx.Response(
        200, json={"data": {"invoice": invoices, "totalCount": len(invoices)}}))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=httpx.Response(
        200, json={"data": {"medicalCards": [], "totalCount": 0}}))
    return route


async def _call(args):
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1)
    with headers, runtime:
        result = await mcp.call_tool("get_inactive_pets", args)
    assert not result.is_error
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
@respx.mock
async def test_pages_resume_inside_owner_and_cross_to_next_owner():
    route = _mock_data([_client(1), _client(2)], {1: [10, 11, 12], 2: [20]}, total=2)
    first = await _call({"limit": 2})
    second = await _call({"limit": 3, "cursor": first["next_cursor"]})
    assert [p["id"] for p in first["inactive_pets"]] == [10, 11]
    assert [p["id"] for p in second["inactive_pets"]] == [12, 20]
    assert first["has_more"] is True and first["next_cursor"]
    assert second["has_more"] is False and second["next_cursor"] is None
    assert first["truncated"] is True and first["truncation_reason"] == "limit_reached"
    assert second["truncated"] is False and second["truncation_reason"] is None
    assert all(k in first for k in ("limit_applied", "clients_scanned", "cutoff_window",
                                      "months_min", "months_max", "safety_cap_reached"))
    assert route.call_count <= 2, "resume must not scan the first client again"
    pet_requests = [call.request for call in respx.calls
                    if call.request.url.path == "/rest/api/pet"]
    assert any(any(clause["property"] == "id" and clause["operator"] == ">"
                   and clause["value"] == 11
                   for clause in json.loads(parse_qs(request.url.query.decode())["filter"][0]))
               for request in pet_requests), "resume must skip previously resolved pet IDs upstream"
    for path in ("/rest/api/pet", "/rest/api/invoice"):
        requests = [call.request for call in respx.calls if call.request.url.path == path]
        assert requests
        assert all(json.loads(parse_qs(request.url.query.decode())["sort"][0]) == [
            {"property": "id", "direction": "ASC"},
        ] for request in requests)


@pytest.mark.asyncio
@respx.mock
async def test_scan_cap_has_unknown_more_and_resumable_cursor(monkeypatch):
    import tools.pet as pet_module
    monkeypatch.setattr(pet_module, "CLIENT_PAGE_SIZE", 1)
    monkeypatch.setattr(pet_module, "MAX_CLIENT_PAGES", 1)
    _mock_data([_client(1), _client(2)], {2: [20]}, total=2)
    first = await _call({"limit": 1})
    assert first["inactive_pets"] == []
    assert first["has_more"] is None and first["next_cursor"]
    assert first["truncation_reason"] == "client_scan_cap"
    second = await _call({"limit": 1, "cursor": first["next_cursor"]})
    assert [p["id"] for p in second["inactive_pets"]] == [20]
    assert second["has_more"] is False


@pytest.mark.asyncio
@respx.mock
async def test_unknown_total_at_scan_cap_does_not_claim_end(monkeypatch):
    import tools.pet as pet_module
    monkeypatch.setattr(pet_module, "CLIENT_PAGE_SIZE", 1)
    monkeypatch.setattr(pet_module, "MAX_CLIENT_PAGES", 1)
    _mock_data([_client(1)], {}, total=None)
    first = await _call({"limit": 1})
    assert first["has_more"] is None and first["next_cursor"]


@pytest.mark.asyncio
@respx.mock
async def test_bad_cursor_and_changed_window_rejected_before_http():
    route = _mock_data([_client(1)], {1: [10, 11]}, total=1)
    first = await _call({"limit": 1})
    for args in ({"cursor": "bad"}, {"cursor": first["next_cursor"] + "!"},
                 {"cursor": first["next_cursor"], "months_min": 4}):
        headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
        with headers, runtime, pytest.raises(Exception):
            await mcp.call_tool("get_inactive_pets", args)
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_large_internal_client_offset_and_stable_sort():
    from tools._inactive_helpers import fetch_inactive_clients_page
    route = _mock_data([], {}, total=20_000)
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime:
        await fetch_inactive_clients_page(1, 24, limit=100, offset=10_001)
    query = parse_qs(route.calls[0].request.url.query.decode())
    assert query["offset"] == ["10001"]
    assert json.loads(query["sort"][0]) == [
        {"property": "last_visit_date", "direction": "DESC"},
        {"property": "id", "direction": "DESC"},
    ]


@pytest.mark.asyncio
@respx.mock
async def test_distinct_days_stop_after_probe(monkeypatch):
    import tools.pet as pet_module
    clients = [_client(i) for i in range(1, 101)]
    for i, client in enumerate(clients):
        client["last_visit_date"] = f"2024-12-{(i % 28) + 1:02d} 12:00:00"
    _mock_data(clients, {}, total=100)
    calls = []

    async def resolve(_vc, *, clients, limit, min_pet_id):
        calls.append(len(clients))
        assert min_pet_id == 0
        cid = clients[0]["id"]
        return [(clients[0], [{"id": cid, "owner_id": cid, "visit_source": "invoice"}])]

    monkeypatch.setattr(pet_module, "find_pets_for_clients_last_visit", resolve)
    data = await _call({"limit": 1})
    assert data["has_more"] is True
    assert calls == [1, 1]

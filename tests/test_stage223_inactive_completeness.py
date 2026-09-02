"""Stage 223: a lapsed-pet list says whether it is the whole list.

`get_inactive_pets` used to answer with `limit_applied: 50` and fifty records.
Those two numbers cannot tell "there are exactly fifty pets in the window" from
"there are five thousand and you are looking at the first fifty" — so a model
reading the answer would honestly report it had found everyone. For a tool used
to build reactivation lists, silently under-reporting is the worst failure it
has: it does not break, it just returns less.
"""

import json

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="mock-token", bearer_token_id=1, connection_id=1
    )


def _client(client_id: int) -> dict:
    return {
        "id": client_id,
        "last_name": f"Owner{client_id}",
        "first_name": "Test",
        "middle_name": "",
        "cell_phone": f"+{client_id:04d}",
        "last_visit_date": "2024-12-15 14:30:00",
    }


def _clients_response(clients: list[dict], total: int | None = None) -> httpx.Response:
    data: dict = {"client": clients}
    if total is not None:
        data["totalCount"] = total
    return httpx.Response(200, json={"data": data})


def _pets_response(pets: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"data": {"totalCount": len(pets), "pet": pets}})


def _invoices_response(invoices: list[dict]) -> httpx.Response:
    return httpx.Response(
        200, json={"data": {"totalCount": len(invoices), "invoice": invoices}}
    )


def _pet(pet_id: int, owner_id: int) -> dict:
    return {
        "id": pet_id,
        "alias": f"Pet{pet_id}",
        "type_id": 1,
        "owner_id": owner_id,
        "status": "alive",
    }


def _invoice(pet_id: int, owner_id: int) -> dict:
    return {
        "id": 1000 + pet_id,
        "pet_id": pet_id,
        "client_id": owner_id,
        "invoice_date": "2024-12-15 15:00:00",
        "doctor_id": 7,
    }


def _mock_one_client_with_pets(pet_ids: list[int], *, clients_total: int | None = 1) -> None:
    """One lapsed client, every pet of theirs confirmed at the visit by an invoice."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_clients_response([_client(1)], total=clients_total)
    )
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pets_response([_pet(pet_id, 1) for pet_id in pet_ids])
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=_invoices_response([_invoice(pet_id, 1) for pet_id in pet_ids])
    )
    respx.get(f"{BASE}/rest/api/user").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"totalCount": 1, "user": [
                {"id": 7, "last_name": "Doctor", "first_name": "Test", "middle_name": ""}
            ]}},
        )
    )


async def _call(tool: str, args: dict) -> dict:
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(tool, args)
    return json.loads(result.content[0].text)


# ── get_inactive_pets ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_a_short_list_is_not_truncated():
    _mock_one_client_with_pets([10, 11])
    data = await _call("get_inactive_pets", {"limit": 50})

    assert len(data["inactive_pets"]) == 2
    assert data["truncated"] is False
    assert data["truncation_reason"] is None


@pytest.mark.asyncio
@respx.mock
async def test_a_list_cut_by_the_limit_says_so():
    _mock_one_client_with_pets([10, 11, 12])
    data = await _call("get_inactive_pets", {"limit": 2})

    assert len(data["inactive_pets"]) == 2, "the probe pet must not leak into the answer"
    assert data["truncated"] is True
    assert data["truncation_reason"] == "limit_reached"


@pytest.mark.asyncio
@respx.mock
async def test_a_list_that_exactly_fills_the_limit_is_not_truncated():
    """The case the `limit + 1` probe exists for: full is not the same as cut."""
    _mock_one_client_with_pets([10, 11])
    data = await _call("get_inactive_pets", {"limit": 2})

    assert len(data["inactive_pets"]) == 2
    assert data["truncated"] is False
    assert data["truncation_reason"] is None


@pytest.mark.asyncio
@respx.mock
async def test_the_window_size_comes_from_upstream_not_from_the_page():
    _mock_one_client_with_pets([10], clients_total=137)
    data = await _call("get_inactive_pets", {"limit": 50})

    assert data["clients_total_in_window"] == 137


@pytest.mark.asyncio
@respx.mock
async def test_a_missing_upstream_total_is_unknown_not_zero():
    """Zero would read as "nobody lapsed"; the honest answer is "not told"."""
    _mock_one_client_with_pets([10], clients_total=None)
    data = await _call("get_inactive_pets", {"limit": 50})

    assert data["clients_total_in_window"] is None


@pytest.mark.asyncio
@respx.mock
async def test_hitting_the_client_scan_cap_truncates_even_with_room_left(monkeypatch):
    """More clients wait beyond the cap, so the answer is short whatever the limit says."""
    import tools.pet as pet_module

    monkeypatch.setattr(pet_module, "CLIENT_PAGE_SIZE", 1)
    monkeypatch.setattr(pet_module, "MAX_CLIENT_PAGES", 1)
    _mock_one_client_with_pets([10], clients_total=500)

    data = await _call("get_inactive_pets", {"limit": 50})

    assert data["safety_cap_reached"] is True
    assert data["truncated"] is True
    assert data["truncation_reason"] == "client_scan_cap"


# ── get_inactive_clients ────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_lapsed_clients_report_the_window_total():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_clients_response([_client(i) for i in range(1, 4)], total=137)
    )

    data = await _call("get_inactive_clients", {"limit": 3})

    assert data["total_in_window"] == 137
    assert data["truncated"] is True


@pytest.mark.asyncio
@respx.mock
async def test_lapsed_clients_that_fit_are_not_truncated():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_clients_response([_client(i) for i in range(1, 4)], total=3)
    )

    data = await _call("get_inactive_clients", {"limit": 50})

    assert data["total_in_window"] == 3
    assert data["truncated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_lapsed_clients_without_an_upstream_total_say_unknown():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_clients_response([_client(1)], total=None)
    )

    data = await _call("get_inactive_clients", {"limit": 50})

    assert data["total_in_window"] is None
    assert data["truncated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_the_probe_costs_one_batched_fallback_not_one_per_client():
    """Reaching one pet further must not turn the fallback into a per-client walk."""
    billing_mock()
    clients = [_client(i) for i in range(1, 21)]
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_clients_response(clients, total=20)
    )
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pets_response([_pet(100 + i, i) for i in range(1, 21)])
    )
    # Nobody has an invoice, so every pet goes through the medcard fallback.
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoices_response([]))
    medcards = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(
            200, json={"data": {"totalCount": 0, "medicalCards": []}}
        )
    )

    await _call("get_inactive_pets", {"limit": 5})

    assert medcards.call_count <= 2, (
        f"fallback called {medcards.call_count} times for 20 clients — "
        "the probe must not unbatch it"
    )

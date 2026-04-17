"""Regression tests for Stage 87 — post-migration consistency sweep.

Baseline super-review 2026-04-17 found that stage 77.4 (Pet FK owner_id),
stage 78.6 (get_invoices.payment_status), and PRD stage 80 ("doctor_id for
timesheet") migrations left legacy names in:

- tools/pet.py::create_pet payload (client_id -> owner_id)
- tools/operations.py::get_timesheets (user_id -> doctor_id, filter instead
  of extra{userId} top-level query)
- prompts.py: book_appointment (client_id -> owner_id), unconfirmed_appointments
  (status filter + date range), unpaid_invoices (payment_status), client_no_visit
  (get_inactive_clients), search_good (title -> name).

These tests pin the updated contracts.
"""

import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"

PROMPTS_SRC = (
    Path(__file__).resolve().parents[1] / "prompts.py"
).read_text(encoding="utf-8")


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


def _filter_of(route) -> list[dict]:
    url = str(route.calls.last.request.url)
    q = parse_qs(urlparse(url).query)
    return json.loads(q["filter"][0]) if "filter" in q else []


def _query_of(route) -> dict:
    url = str(route.calls.last.request.url)
    q = parse_qs(urlparse(url).query)
    return {k: v[0] for k, v in q.items()}


# ── tools/pet.py::create_pet ────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_create_pet_payload_uses_owner_id():
    """create_pet must POST payload with owner_id (not legacy client_id)."""
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 77}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_pet",
            {"alias": "Barney", "owner_id": 42, "type_id": 1},
        )

    body = _body_of(route)
    assert body["owner_id"] == 42
    assert body["alias"] == "Barney"
    assert "client_id" not in body


# ── tools/operations.py::get_timesheets ──────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_timesheets_uses_doctor_id_filter():
    """get_timesheets must pass doctor_id via filter[], not extra{userId}."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": 1, "doctor_id": 7}]}
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_timesheets", {"doctor_id": 7, "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "doctor_id" and f.get("value") == 7
        for f in filters
    ), f"expected doctor_id=7 filter, got {filters}"

    # Must NOT send the legacy top-level userId query param.
    query = _query_of(route)
    assert "userId" not in query


@pytest.mark.asyncio
@respx.mock
async def test_get_timesheets_without_doctor_id_sends_no_filter():
    """If doctor_id=0 (default), no doctor_id filter is appended."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_timesheets", {"limit": 10})

    filters = _filter_of(route)
    assert not any(f.get("property") == "doctor_id" for f in filters)


# ── prompts.py: sweep verification ──────────────────────────────────────────


class TestStage87PromptSweep:
    def test_book_appointment_uses_owner_id(self):
        """book_appointment must instruct get_pets(owner_id=...), not client_id=..."""
        assert "get_pets(owner_id=client_id" in PROMPTS_SRC
        assert "get_pets(client_id=client_id" not in PROMPTS_SRC

    def test_unconfirmed_appointments_uses_status_filter(self):
        """unconfirmed_appointments must pass status='not_confirmed' at API level
        and use a date range, not client-side filtering."""
        # Find the prompt body
        assert "status='not_confirmed'" in PROMPTS_SRC
        # Must use date_from/date_to range; must NOT use pseudocode `date+2d`
        # literal (non-executable math that LLM might emit verbatim).
        # Stage 102.3 computes end_date in Python; prompt contains
        # `date_from='{start_iso}'` and `date_to='{end_date}'` f-string template.
        assert "date_from=" in PROMPTS_SRC
        assert "date_to=" in PROMPTS_SRC
        assert "date+2d" not in PROMPTS_SRC

    def test_unpaid_invoices_uses_payment_status_param(self):
        """unpaid_invoices must call get_invoices(payment_status='none'/'partial')
        instead of client-side filtering."""
        assert "payment_status='none'" in PROMPTS_SRC
        assert "payment_status='partial'" in PROMPTS_SRC

    def test_client_no_visit_uses_get_inactive_clients(self):
        """client_no_visit must use the specialized get_inactive_clients tool,
        not manual post-processing of get_admissions."""
        assert "get_inactive_clients(" in PROMPTS_SRC
        # The old body called get_admissions and walked the list manually;
        # verify the new prompt text replaced it.
        client_no_visit_snippet_start = PROMPTS_SRC.index("def client_no_visit")
        client_no_visit_body = PROMPTS_SRC[
            client_no_visit_snippet_start : client_no_visit_snippet_start + 700
        ]
        assert "get_admissions" not in client_no_visit_body
        assert "get_inactive_clients" in client_no_visit_body

    def test_search_good_uses_title_param(self):
        """search_good prompt must call get_goods(title=...) — the `name` param
        is legacy and less accurate."""
        search_good_start = PROMPTS_SRC.index("def search_good")
        search_good_body = PROMPTS_SRC[search_good_start : search_good_start + 500]
        assert "get_goods(title=query" in search_good_body
        assert "get_goods(name=query" not in search_good_body

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
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"

# Stage 109.4: removed dead `PROMPTS_SRC = Path(...).read_text()` module-level
# load — never used by any test in this file, but crashed collection if
# prompts.py moved (future subpackage reorg).


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


async def _render_prompt_body(prompt_name: str, **kwargs) -> str:
    """Stage 101.9: render a registered prompt to plain text via FastMCP's
    registry so tests survive refactors of the prompt-source file layout.
    Async helper — uses caller's event loop (pytest-asyncio)."""
    from server import mcp

    prompt_obj = await mcp.get_prompt(prompt_name)
    assert prompt_obj is not None, f"prompt {prompt_name} not registered"
    rendered = await prompt_obj.render(arguments=kwargs)
    messages: list = []
    for tpl in rendered:
        if isinstance(tpl, tuple) and len(tpl) == 2 and tpl[0] == "messages":
            messages = tpl[1]
            break
    return "\n".join(
        m.content.text for m in messages
        if hasattr(m, "content") and hasattr(m.content, "text")
    )


class TestStage87PromptSweep:
    """Stage 101.9: prompt bodies asserted via rendered MCP Message content,
    not via substring-match on module source."""

    @pytest.mark.asyncio
    async def test_book_appointment_uses_owner_id(self):
        body = await _render_prompt_body(
            "book_appointment",
            client_name="X", pet_name="Y", doctor_id=1, date="2026-01-01",
        )
        assert "get_pets(owner_id=client_id" in body
        assert "get_pets(client_id=client_id" not in body

    @pytest.mark.asyncio
    async def test_unconfirmed_appointments_uses_status_filter(self):
        body = await _render_prompt_body(
            "unconfirmed_appointments", date="2026-01-01",
        )
        assert "status='not_confirmed'" in body
        assert "date_from=" in body
        assert "date_to=" in body
        assert "date+2d" not in body

    @pytest.mark.asyncio
    async def test_unpaid_invoices_uses_payment_status_param(self):
        body = await _render_prompt_body("unpaid_invoices")
        assert "payment_status='none'" in body
        assert "payment_status='partial'" in body

    @pytest.mark.asyncio
    async def test_client_no_visit_uses_get_inactive_clients(self):
        body = await _render_prompt_body("client_no_visit")
        assert "get_inactive_clients(" in body
        assert "get_admissions" not in body

    @pytest.mark.asyncio
    async def test_search_good_uses_title_param(self):
        body = await _render_prompt_body("search_good", query="vaccine")
        assert "get_goods(title=" in body
        assert "get_goods(name=" not in body

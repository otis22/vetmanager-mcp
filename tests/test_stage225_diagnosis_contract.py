"""Stage 225 — the diagnosis field of a medical card is a reference, not text.

Live probe on devtr6 (2026-09-01, card 818) established the contract:
`diagnos` holds a JSON array string of `{"id", "type"}`, where `id` comes from
`/rest/api/MedicalCards/AllDiagnoses` and `type` from the `diagnos_types`
combo manual (1 final, 2 preliminary, 3 differential, 4 probable). A value that
JSON-decodes to an integer answers HTTP 500 and is not saved; free text answers
201 and is stored verbatim, silently corrupting the field. These tests pin the
tool contract that makes both outcomes impossible from our side.
"""

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError, ValidationError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"
CARD_ID = 42


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="mock-token", bearer_token_id=1, connection_id=1,
    )


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


def _card_read_mock():
    return respx.get(f"{BASE}/rest/api/MedicalCards/{CARD_ID}").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 1, "medicalCards": {
            "id": CARD_ID, "patient_id": 7, "doctor_id": 8, "clinic_id": 9,
        }}})
    )


def _create_route():
    return respx.post(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(201, json={"data": {"id": 105}})
    )


def _update_route():
    return respx.put(f"{BASE}/rest/api/MedicalCards/{CARD_ID}").mock(
        return_value=httpx.Response(200, json={"data": {"id": CARD_ID}})
    )


CREATE_BASE = {"patient_id": 5, "doctor_id": 3, "date_create": "2026-04-20"}


async def _call(tool: str, args: dict):
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        return await mcp.call_tool(tool, args)


# ── the shape that reaches the API ──────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_create_sends_diagnosis_ids_as_a_json_array_string():
    billing_mock()
    route = _create_route()
    await _call("create_medical_card", {**CREATE_BASE, "diagnosis_ids": [32, 11]})

    body = _body_of(route)
    assert isinstance(body["diagnos"], str)
    assert json.loads(body["diagnos"]) == [{"id": 32, "type": 1}, {"id": 11, "type": 1}]
    assert "diagnosis_ids" not in body
    assert "diagnosis" not in body


@pytest.mark.asyncio
@respx.mock
async def test_update_sends_diagnosis_ids_with_the_requested_type():
    billing_mock()
    _card_read_mock()
    route = _update_route()
    await _call("update_medical_card", {
        "card_id": CARD_ID, "diagnosis_ids": [19], "diagnosis_type": 2,
    })

    body = _body_of(route)
    assert json.loads(body["diagnos"]) == [{"id": 19, "type": 2}]


@pytest.mark.asyncio
@respx.mock
async def test_free_text_goes_to_its_own_field_and_never_to_diagnos():
    billing_mock()
    _card_read_mock()
    route = _update_route()
    await _call("update_medical_card", {"card_id": CARD_ID, "diagnosis_text": "гастрит"})

    body = _body_of(route)
    assert body["diagnos_text"] == "гастрит"
    assert "diagnos" not in body


@pytest.mark.asyncio
@respx.mock
async def test_free_text_on_create_is_refused_because_upstream_drops_it():
    """Verified on devtr6 2026-09-01: POST answers 201 and stores an empty
    `diagnos_text`, while PUT stores it. Accepting the argument here would
    promise the clinic a note it never gets."""
    billing_mock()
    route = _create_route()
    with pytest.raises(ToolError) as excinfo:
        await _call("create_medical_card", {**CREATE_BASE, "diagnosis_text": "гастрит"})
    assert "update_medical_card" in str(excinfo.value)
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_no_diagnosis_argument_leaves_both_fields_alone():
    billing_mock()
    route = _create_route()
    await _call("create_medical_card", {**CREATE_BASE, "description": "Осмотр"})

    body = _body_of(route)
    assert "diagnos" not in body
    assert "diagnos_text" not in body


# ── refusals that happen before any request ─────────────────────────────────

@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("ids", [
    pytest.param([], id="empty-list"),
    pytest.param([0], id="zero"),
    pytest.param([-3], id="negative"),
])
async def test_bad_diagnosis_ids_are_refused_by_the_tool_with_a_pointer(ids):
    billing_mock()
    route = _create_route()
    with pytest.raises(ToolError) as excinfo:
        await _call("create_medical_card", {**CREATE_BASE, "diagnosis_ids": ids})
    assert "diagnosis_ids" in str(excinfo.value)
    assert not route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("ids", [
    pytest.param([True], id="bool-is-not-an-id"),
    pytest.param([32, True], id="bool-among-valid"),
    pytest.param(["32"], id="string-that-looks-numeric"),
])
async def test_non_integer_ids_are_refused_by_the_schema(ids):
    """Pydantic accepts True as the integer 1 unless the field is strict, and
    diagnosis id 1 is a real diagnosis in a real clinic."""
    billing_mock()
    route = _create_route()
    with pytest.raises(ValidationError):
        await _call("create_medical_card", {**CREATE_BASE, "diagnosis_ids": ids})
    assert not route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("diagnosis_type", [0, 5, -1])
async def test_unknown_diagnosis_type_is_refused_with_the_allowed_values(diagnosis_type):
    billing_mock()
    route = _create_route()
    with pytest.raises(ToolError) as excinfo:
        await _call("create_medical_card", {
            **CREATE_BASE, "diagnosis_ids": [32], "diagnosis_type": diagnosis_type,
        })
    assert "1" in str(excinfo.value) and "4" in str(excinfo.value)
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_empty_list_refusal_says_erasing_is_not_supported():
    billing_mock()
    _create_route()
    with pytest.raises(ToolError) as excinfo:
        await _call("create_medical_card", {**CREATE_BASE, "diagnosis_ids": []})
    assert "diagnosis_ids" in str(excinfo.value)


# ── the old parameter is a trap, not a path ─────────────────────────────────

LEGACY_VALUES = [
    pytest.param("32", id="number-as-text"),
    pytest.param("гастрит", id="free-text"),
    pytest.param('[{"id":32,"type":1}]', id="hand-built-json"),
    pytest.param("[32]", id="json-array-of-ids"),
]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("value", LEGACY_VALUES)
async def test_legacy_diagnosis_argument_is_refused_with_a_pointer(value):
    billing_mock()
    route = _create_route()
    with pytest.raises(ToolError) as excinfo:
        await _call("create_medical_card", {**CREATE_BASE, "diagnosis": value})
    message = str(excinfo.value)
    assert "diagnosis_ids" in message and "diagnosis_text" in message
    assert not route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("value", LEGACY_VALUES)
async def test_legacy_diagnosis_argument_is_refused_on_update_too(value):
    billing_mock()
    _card_read_mock()
    route = _update_route()
    with pytest.raises(ToolError):
        await _call("update_medical_card", {"card_id": CARD_ID, "diagnosis": value})
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_empty_legacy_diagnosis_changes_nothing_and_is_not_an_error():
    billing_mock()
    route = _create_route()
    await _call("create_medical_card", {**CREATE_BASE, "diagnosis": "", "description": "Осмотр"})

    body = _body_of(route)
    assert "diagnos" not in body


# ── the invariant itself ────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("args", [
    {"diagnosis_ids": [32]},
    {"diagnosis_ids": [32, 11], "diagnosis_type": 3},
    {"diagnosis": ""},
    {"description": "Осмотр"},
])
async def test_diagnos_never_carries_a_value_that_decodes_to_an_integer(args):
    """The exact upstream trigger: a `diagnos` that JSON-decodes to an int."""
    billing_mock()
    route = _create_route()
    await _call("create_medical_card", {**CREATE_BASE, **args})

    sent = _body_of(route).get("diagnos")
    if sent is None:
        return
    assert isinstance(sent, str)
    decoded = json.loads(sent)
    assert isinstance(decoded, list)
    assert all(isinstance(item, dict) and set(item) == {"id", "type"} for item in decoded)
    assert all(isinstance(item["id"], int) and not isinstance(item["id"], bool) for item in decoded)

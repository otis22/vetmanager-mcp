"""Live check for stage 225: the diagnosis field is written as a reference.

The contract was established by probing devtr6 on 2026-09-01 (card 818):
`diagnos` holds a JSON array string of `{"id", "type"}`; a value that decodes
to a bare integer answers HTTP 500 and is not saved; free text answers 201 and
is stored verbatim. This test drives the same path through the tool.

Non-polluting: the card is created by the test, and the diagnosis it carries is
restored to what the test itself wrote first. Nothing pre-existing is touched.

Run against the dedicated test contour:

    docker compose --profile test run --rm -T test pytest -m real_api \\
        tests/test_stage225_live_diagnosis_contract.py
"""

import json
import os

import pytest
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import (
    make_client_with_resolved_runtime,
    patch_runtime_credentials,
)

TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")

skip_if_no_creds = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_API_KEY,
    reason="TEST_DOMAIN and TEST_API_KEY not set — skipping real API tests",
)

_MC_ENDPOINT = "/rest/api/MedicalCards"
_DIAGNOSES_ENDPOINT = "/rest/api/MedicalCards/AllDiagnoses"
MARKER = "MCP live check stage 225"


def _client():
    return make_client_with_resolved_runtime(TEST_DOMAIN, TEST_API_KEY)


async def _read(card_id: int) -> dict:
    response = await _client().get(f"{_MC_ENDPOINT}/{card_id}")
    record = response.get("data", {}).get("medicalCards")
    if isinstance(record, list):
        record = record[0] if record else None
    if not isinstance(record, dict):
        pytest.skip("Medical-card read returned no record.")
    return record


async def _some_diagnosis_ids(count: int) -> list[int]:
    response = await _client().get(_DIAGNOSES_ENDPOINT, params={"limit": count, "offset": 0})
    rows = response.get("data", {}).get("diagnoses") or []
    ids = [int(row["id"]) for row in rows if isinstance(row, dict) and row.get("id")]
    if len(ids) < count:
        pytest.skip("Diagnosis catalogue on this contour is too small for the check.")
    return ids[:count]


async def _card_context() -> dict:
    listing = await _client().get(_MC_ENDPOINT, params={"limit": 20, "offset": 0})
    records = listing.get("data", {}).get("medicalCards") or []
    for record in records:
        if all(record.get(field) for field in ("patient_id", "doctor_id", "clinic_id")):
            return record
    pytest.skip("No medical card with patient/doctor/clinic context on this contour.")


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_diagnosis_ids_are_stored_as_a_reference_array() -> None:
    context = await _card_context()
    ids = await _some_diagnosis_ids(2)

    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        created = await mcp.call_tool("create_medical_card", {
            "patient_id": int(context["patient_id"]),
            "doctor_id": int(context["doctor_id"]),
            "clinic_id": int(context["clinic_id"]),
            "date_create": "2026-09-01 12:00:00",
            "description": MARKER,
            "diagnosis_ids": ids[:1],
        })

    rows = created.structured_content["data"]["medicalCards"]
    card_id = int(rows[0]["id"] if isinstance(rows, list) else rows["id"])
    stored = await _read(card_id)
    assert json.loads(stored["diagnos"]) == [{"id": ids[0], "type": 1}]

    with headers_patch, runtime_patch:
        await mcp.call_tool("update_medical_card", {
            "card_id": card_id, "diagnosis_ids": ids, "diagnosis_type": 2,
        })
    stored = await _read(card_id)
    assert json.loads(stored["diagnos"]) == [{"id": ids[0], "type": 2}, {"id": ids[1], "type": 2}]

    with headers_patch, runtime_patch:
        await mcp.call_tool("update_medical_card", {
            "card_id": card_id, "diagnosis_text": "уточняется",
        })
    stored = await _read(card_id)
    assert stored["diagnos_text"] == "уточняется"
    assert json.loads(stored["diagnos"]) == [{"id": ids[0], "type": 2}, {"id": ids[1], "type": 2}]


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_upstream_still_refuses_a_bare_number_in_diagnos() -> None:
    """The defect reported to Vetmanager is still there.

    When it is fixed, this test fails and the local guard can be reconsidered
    instead of being carried forever.
    """
    context = await _card_context()
    ids = await _some_diagnosis_ids(1)
    payload = {field: context[field] for field in ("patient_id", "doctor_id", "clinic_id")}
    payload["diagnos"] = str(ids[0])

    from exceptions import VetmanagerError

    with pytest.raises(VetmanagerError) as raised:
        await _client().put(f"{_MC_ENDPOINT}/{int(context['id'])}", json=payload)
    assert raised.value.status_code == 500


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_tool_refuses_the_bad_shapes_before_reaching_upstream() -> None:
    context = await _card_context()
    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        for args in (
            {"diagnosis_ids": [], "diagnosis_type": 1},
            {"diagnosis_ids": [1], "diagnosis_type": 9},
            {"diagnosis": "гастрит"},
        ):
            with pytest.raises(ToolError):
                await mcp.call_tool("update_medical_card", {
                    "card_id": int(context["id"]), **args,
                })
        with pytest.raises(ToolError):
            await mcp.call_tool("create_medical_card", {
                "patient_id": int(context["patient_id"]),
                "doctor_id": int(context["doctor_id"]),
                "date_create": "2026-09-01 12:00:00",
                "diagnosis_text": "не сохранится при создании",
            })

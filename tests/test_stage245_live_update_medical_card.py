"""Live write-path check for stage 245: update_medical_card on a real contour.

Stage 245 shipped the fix that carries `patient_id`, `doctor_id` and `clinic_id`
from the stored record into the PUT body, because Vetmanager rejects a partial
medical-card update with `400 Patient does not exist`. That fix was verified by
hand with raw REST on 2026-08-23; this test makes the same verification
repeatable through the tool itself.

Non-polluting: the original value is restored and the restoration is asserted.

Run against the dedicated test contour:

    docker compose --profile test run --rm -T test pytest -m real_api \\
        tests/test_stage245_live_update_medical_card.py
"""

import os

import pytest

from server import mcp
from exceptions import VetmanagerError
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

MARKER = "MCP live check stage 245"
_MC_ENDPOINT = "/rest/api/MedicalCards"
_REQUIRED_CONTEXT = ("patient_id", "doctor_id", "clinic_id")


def _client():
    return make_client_with_resolved_runtime(TEST_DOMAIN, TEST_API_KEY)


def _unwrap(response: dict) -> dict:
    """Singleton medical-card reads arrive under `data.medicalCards`."""
    data = response.get("data")
    if not isinstance(data, dict):
        pytest.skip("Unexpected medical-card response shape.")
    record = data.get("medicalCards")
    if isinstance(record, list):
        record = record[0] if record else None
    if not isinstance(record, dict):
        pytest.skip("Medical-card read returned no record.")
    return record


async def _pick_card() -> dict:
    """First card that carries the context the write path needs."""
    listing = await _client().get(_MC_ENDPOINT, params={"limit": 20, "offset": 0})
    data = listing.get("data", {})
    records = data.get("medicalCards") or data.get("medicalcards") or []
    for record in records:
        if all(record.get(field) for field in _REQUIRED_CONTEXT):
            return record
    pytest.skip("No medical card with patient/doctor/clinic context on this contour.")


async def _read(card_id: int) -> dict:
    return _unwrap(await _client().get(f"{_MC_ENDPOINT}/{card_id}"))


async def _restore(card: dict, original: str) -> None:
    """Put the original value back, including an empty one the tool cannot send."""
    payload = {field: card[field] for field in _REQUIRED_CONTEXT}
    payload["recomendation"] = original
    await _client().put(f"{_MC_ENDPOINT}/{card['id']}", json=payload)


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_update_medical_card_writes_single_field_and_restores() -> None:
    card = await _pick_card()
    card_id = int(card["id"])
    original = str(card.get("recomendation") or "")

    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    try:
        with headers_patch, runtime_patch:
            await mcp.call_tool(
                "update_medical_card",
                {"card_id": card_id, "recomendation": MARKER},
            )
        written = await _read(card_id)
        assert MARKER in str(written.get("recomendation") or "")
    finally:
        await _restore(card, original)

    restored = await _read(card_id)
    assert str(restored.get("recomendation") or "") == original


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_partial_medical_card_put_is_still_rejected_upstream() -> None:
    """The upstream barrier the fix works around is still in place.

    If Vetmanager ever starts accepting a partial body, this test fails and the
    workaround can be reconsidered instead of being carried forever.
    """
    card = await _pick_card()
    with pytest.raises(VetmanagerError) as exc_info:
        await _client().put(
            f"{_MC_ENDPOINT}/{card['id']}",
            json={"recomendation": MARKER},
        )
    assert "patient" in str(exc_info.value).lower()

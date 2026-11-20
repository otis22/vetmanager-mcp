"""Live, reversible privacy probe on the dedicated API-key test contour."""

import hashlib
import os

import pytest

from server import mcp
from tests.runtime_factories import make_client_with_resolved_runtime, patch_runtime_credentials


TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")
_ENDPOINT = "/rest/api/MedicalCards"
_PROBE = (
    "stage361: таблица диуреза\n"
    "Показатели: 120 100 80 60\n"
    "Единица: мл\n"
    "Примечание: тел. 000 000 00 00"
)
def _card(response: object) -> dict:
    if not isinstance(response, dict):
        return {}
    data = response.get("data", {})
    card = data.get("medicalCards") if isinstance(data, dict) else None
    if isinstance(card, list):
        card = card[0] if card else None
    return card if isinstance(card, dict) else {}


def _technical_summary(label: str, card_id: int, response: dict) -> None:
    """Print only technical data to the private, non-published real-run evidence."""
    card = _card(response)
    description = str(card.get("description") or "")
    digest = hashlib.sha256(description.encode("utf-8")).hexdigest()
    response_status = response.get("status") if isinstance(response, dict) else None
    status = response_status if type(response_status) is int else "http_success"
    print(
        f"stage361_{label} id={card_id} status={status} "
        f"card_present={bool(card)} card_id_matches={str(card.get('id')) == str(card_id)} "
        f"description_length={len(description)} description_sha256={digest} "
        f"probe_marker={_PROBE in description} "
        f"clinical_row={'Показатели: 120 100 80 60' in description} "
        f"phone_marker={'Примечание: тел. [redacted-phone]' in description}",
        flush=True,
    )


@pytest.mark.real_api
def test_summary_never_prints_upstream_description_or_response_data(capsys) -> None:
    private_text = "patient secret token stage361: таблица диуреза"
    _technical_summary(
        "put", 7,
        {"status": 200, "message": private_text, "data": {"medicalCards": {
            "id": 7, "description": private_text,
        }}},
    )
    output = capsys.readouterr().out
    assert private_text not in output
    assert "patient secret token" not in output
    assert "id=7 status=200" in output
    assert f"description_length={len(private_text)}" in output
    assert "description_sha256=" in output


@pytest.mark.real_api
def test_summary_handles_put_without_card_body(capsys) -> None:
    _technical_summary("put", 7, {"status": 200, "data": {}})
    assert "card_present=False" in capsys.readouterr().out


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(
    TEST_DOMAIN != "devtr6" or not TEST_API_KEY,
    reason="Stage 361 live write/restore runs only on the devtr6 API-key test contour",
)
async def test_live_medical_card_numeric_row_and_marked_phone() -> None:
    client = make_client_with_resolved_runtime(TEST_DOMAIN, TEST_API_KEY)
    listing = await client.get(_ENDPOINT, params={"limit": 20, "offset": 0})
    cards = listing.get("data", {}).get("medicalCards") or []
    required = ("patient_id", "doctor_id", "clinic_id")
    card_id = next((int(row["id"]) for row in cards if all(row.get(k) for k in required)), None)
    if card_id is None:
        pytest.skip("No card with safe update context on devtr6")

    original = _card(await client.get(f"{_ENDPOINT}/{card_id}", fresh=True))
    if "description" not in original or not all(original.get(k) for k in required):
        pytest.skip("Stored card lacks description or update context")
    baseline = str(original.get("description") or "")
    _technical_summary("baseline", card_id, {"data": {"medicalCards": original}})
    probe = baseline + "\n" + _PROBE
    payload = {key: original[key] for key in required}
    try:
        put_response = await client.put(f"{_ENDPOINT}/{card_id}", json={**payload, "description": probe})
        _technical_summary("put", card_id, put_response)
        direct_response = await client.get(f"{_ENDPOINT}/{card_id}", fresh=True)
        _technical_summary("fresh_get", card_id, direct_response)
        headers_patch, runtime_patch = patch_runtime_credentials(
            TEST_DOMAIN, TEST_API_KEY, is_depersonalized=True,
        )
        with headers_patch, runtime_patch:
            result = await mcp.call_tool("get_medical_card_by_id", {"card_id": card_id})
        _technical_summary("mcp_get", card_id, result.structured_content or {})
        print(f"stage361_mcp_error={result.is_error}", flush=True)
        assert not result.is_error
        direct = str(_card(direct_response).get("description") or "")
        assert direct == probe, "Fresh upstream GET did not return the written probe"
        cleaned = str(_card(result.structured_content).get("description") or "")
        assert "Показатели: 120 100 80 60\nЕдиница: мл" in cleaned
        assert "Примечание: тел. [redacted-phone]" in cleaned
        assert "000 000 00 00" not in cleaned
        print("stage361_live_mcp_code=success", flush=True)
    finally:
        current = _card(await client.get(f"{_ENDPOINT}/{card_id}", fresh=True))
        current_description = str(current.get("description") or "")
        if current_description == probe:
            restore_response = await client.put(f"{_ENDPOINT}/{card_id}", json={**payload, "description": baseline})
            _technical_summary("restore_put", card_id, restore_response)
        elif current_description != baseline:
            pytest.fail("Test card changed concurrently; preserving the newer content")
        restored = _card(await client.get(f"{_ENDPOINT}/{card_id}", fresh=True))
        _technical_summary("restore_get", card_id, {"data": {"medicalCards": restored}})
        assert str(restored.get("description") or "") == baseline

"""Live, reversible privacy probe on the dedicated API-key test contour."""

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
_OLD_PROBES = (
    "stage361: показатели 120 100 80 60; тел. 912 345 67 89",
    "stage361: показатели 120 100 80 60; тел. 000 000 00 00",
    "stage361: таблица диуреза\nПоказатели: 120 100 80 60 мл\n"
    "Примечание: тел. 000 000 00 00",
)


def _card(response: dict) -> dict:
    data = response.get("data", {})
    card = data.get("medicalCards") if isinstance(data, dict) else None
    if isinstance(card, list):
        card = card[0] if card else None
    return card if isinstance(card, dict) else {}


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

    original = _card(await client.get(f"{_ENDPOINT}/{card_id}"))
    if "description" not in original or not all(original.get(k) for k in required):
        pytest.skip("Stored card lacks description or update context")
    baseline = str(original.get("description") or "")
    for stale_probe in (_PROBE, *_OLD_PROBES):
        if baseline.endswith("\n" + stale_probe):
            baseline = baseline[:-(len(stale_probe) + 1)]
            await client.put(
                f"{_ENDPOINT}/{card_id}",
                json={**{key: original[key] for key in required}, "description": baseline},
            )
            cleaned = _card(await client.get(f"{_ENDPOINT}/{card_id}"))
            assert str(cleaned.get("description") or "") == baseline
            break
    probe = baseline + "\n" + _PROBE
    payload = {key: original[key] for key in required}
    try:
        await client.put(f"{_ENDPOINT}/{card_id}", json={**payload, "description": probe})
        headers_patch, runtime_patch = patch_runtime_credentials(
            TEST_DOMAIN, TEST_API_KEY, is_depersonalized=True,
        )
        with headers_patch, runtime_patch:
            result = await mcp.call_tool("get_medical_card_by_id", {"card_id": card_id})
        assert not result.is_error
        cleaned = str(_card(result.structured_content).get("description") or "")
        assert "Показатели: 120 100 80 60\nЕдиница: мл" in cleaned
        assert "Примечание: тел. [redacted-phone]" in cleaned
        assert "000 000 00 00" not in cleaned
        print("stage361_live_mcp_code=success body=stage361: таблица диуреза | Показатели: 120 100 80 60 | Единица: мл | Примечание: тел. [redacted-phone]")
    finally:
        current = _card(await client.get(f"{_ENDPOINT}/{card_id}"))
        current_description = str(current.get("description") or "")
        if current_description == probe:
            await client.put(f"{_ENDPOINT}/{card_id}", json={**payload, "description": baseline})
        elif current_description != baseline:
            pytest.fail("Test card changed concurrently; preserving the newer content")
        restored = _card(await client.get(f"{_ENDPOINT}/{card_id}"))
        assert str(restored.get("description") or "") == baseline

"""Live guard for stage 247.5: the shape of a medical-card update response.

Vetmanager answers a successful update with `201`, returns only the fields that
were sent, and names the payload key differently than a read does. None of that
loses data, but our code carries a double lookup because of it, and the vendor
task 12353 asks for the contract to be aligned.

These assertions therefore describe what is wrong today. When the vendor fixes
it, this test fails — and that failure is the signal to drop the workaround
rather than carry it forever.

Run against the dedicated test contour:

    docker compose --profile test run --rm -T test pytest -m real_api \\
        tests/test_stage247_live_update_contract.py
"""

import os

import pytest

from host_resolver import resolve_vetmanager_host

TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")

skip_if_no_creds = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_API_KEY,
    reason="TEST_DOMAIN and TEST_API_KEY not set — skipping real API tests",
)

MARKER = "MCP live check stage 247"
_CARD_PATH = "/rest/api/MedicalCards"
_CONTEXT = ("patient_id", "doctor_id", "clinic_id")


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_update_response_contract_still_differs_from_the_read() -> None:
    import httpx

    host = await resolve_vetmanager_host(TEST_DOMAIN)
    headers = {"X-REST-API-KEY": TEST_API_KEY, "X-USE-XALLHEADER": "true"}
    async with httpx.AsyncClient(base_url=host, headers=headers, timeout=30) as client:
        listing = (await client.get(_CARD_PATH, params={"limit": 20, "offset": 0})).json()
        records = listing.get("data", {}).get("medicalCards") or []
        card = next((r for r in records if all(r.get(f) for f in _CONTEXT)), None)
        if card is None:
            pytest.skip("No medical card with patient/doctor/clinic context on this contour.")

        card_id = int(card["id"])
        read = (await client.get(f"{_CARD_PATH}/{card_id}")).json()
        stored = read["data"]["medicalCards"]
        stored = stored[0] if isinstance(stored, list) else stored
        if "recomendation" not in stored:
            pytest.skip("Stored card does not expose `recomendation`; refusing to write.")
        original = str(stored.get("recomendation") or "")

        body = {field: stored[field] for field in _CONTEXT}
        body["recomendation"] = MARKER
        written = None
        try:
            written = await client.put(f"{_CARD_PATH}/{card_id}", json=body)
        finally:
            body["recomendation"] = original
            await client.put(f"{_CARD_PATH}/{card_id}", json=body)

        assert written is not None
        payload = written.json()

        # 1. A successful update answers 201 Created.
        assert written.status_code == 201, (
            "Vetmanager now answers an update with "
            f"{written.status_code} — task 12353 may be fixed; drop the workaround."
        )

        # 2. The write payload key is lowercase where the read key is camelCase.
        data = payload["data"]
        assert "medicalcards" in data, (
            "The write key changed — check whether it now matches the read key "
            "`medicalCards`, and simplify tools/medical_card.py if so."
        )

        # 3. The write echoes only what was sent (plus the derived client_id),
        #    so it cannot be used as the record's new state.
        echoed = data["medicalcards"]
        assert set(echoed) <= set(body) | {"client_id"}, (
            "The write response now carries more than the sent fields — it may "
            "have become a full record; re-check whether the extra read is still needed."
        )
        assert len(echoed) < len(stored)

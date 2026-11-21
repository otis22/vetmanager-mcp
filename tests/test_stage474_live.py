"""Read-only devtr6 proof for the stage 474 history tool."""
import os
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient

pytestmark = pytest.mark.real_api


@pytest.mark.asyncio
@pytest.mark.skipif(os.environ.get("TEST_DOMAIN") != "devtr6" or not os.environ.get("TEST_API_KEY"),
                    reason="devtr6 test contour unavailable")
async def test_stage474_live_discharge_history(capsys):
    headers, runtime = patch_runtime_credentials(os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"])
    observed = []
    original = httpx.AsyncClient.request

    async def capture(client, method, url, **kwargs):
        response = await original(client, method, url, **kwargs)
        if "/rest/api/" in str(url):
            parts = str(url).split("/rest/api/")[1].split("?")[0].split("/")
            resource = "MedicalCards/Vaccinations" if parts[:2] == ["MedicalCards", "Vaccinations"] else parts[0]
            observed.append((method, resource, response.status_code))
        return response

    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        sample = await VetmanagerClient().get("/rest/api/MedicalCards", params={"limit": 1, "offset": 0})
        cards = sample["data"].get("medicalCards") or sample["data"].get("medicalcards") or []
        assert cards
        pet_id = int(cards[0]["patient_id"])
        day = str(cards[0]["date_create"])[:10]
        answer = await mcp.call_tool("get_pet_discharge_history", {
            "pet_id": pet_id, "date_from": day, "date_to": day})
    assert not answer.is_error
    body = answer.structured_content
    assert body["pet_id"] == pet_id
    assert all(section in body for section in (
        "pet", "admissions", "medical_cards", "hospitalizations", "vaccinations", "invoices"))
    required = {"pet", "admission", "MedicalCards", "hospital", "MedicalCards/Vaccinations"}
    if "invoices:finance.read_required" not in body["invoices"]["gaps"]:
        required.add("invoice")
    assert required <= {path for _, path, _ in observed}
    assert all(method == "GET" and status == 200 for method, path, status in observed if path in required)
    assert body["pet"]["count"] == 1
    assert body["medical_cards"]["count"] >= 1
    assert not any("read_failed" in gap or "parent_filter_mismatch" in gap for gap in body["gaps"])
    with capsys.disabled():
        print("STAGE474_LIVE body=" + str({
            "success": not answer.is_error,
            "sections": {section: {"count": body[section]["count"], "complete": body[section]["complete"]}
                         for section in ("pet", "admissions", "medical_cards", "hospitalizations", "vaccinations", "invoices")},
            "gap_codes": [gap.rsplit(":", 1)[-1] for gap in body["gaps"]],
            "http": observed,
        }))

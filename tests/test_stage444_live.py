"""Read-only projection calls on the .env test contour; output has no clinic data."""

import os
import calendar
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient

pytestmark = pytest.mark.real_api


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env test contour unavailable")
async def test_stage444_live_projected_lists(capsys):
    domain, api_key = os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"]
    headers, runtime = patch_runtime_credentials(domain, api_key)
    observed = []
    original = httpx.AsyncClient.request

    async def capture(client, method, url, **kwargs):
        response = await original(client, method, url, **kwargs)
        if "/rest/api/" in str(url):
            observed.append((method, response.status_code))
        return response

    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        latest = await VetmanagerClient().get("/rest/api/MedicalCards", params={
            "limit": 1, "sort": '[{"property":"date_create","direction":"DESC"}]'})
        rows = latest.get("data", {}).get("medicalCards") or []
        assert rows, "test contour needs a medical-card row"
        card = rows[0]
        day = str(card["date_create"])[:10]
        pet_id = int(card["patient_id"])
        per_pet = await mcp.call_tool("get_medical_cards", {
            "pet_id": pet_id, "limit": 1, "fields": ["id", "pet_id", "date_create"]})
        by_date = await mcp.call_tool("get_medical_cards_by_date", {
            "date": day, "limit": 1, "fields": ["id", "pet_id", "date_create"]})
        pets = await VetmanagerClient().get("/rest/api/pet", params={"limit": 100})
        owner = next((row.get("owner_id") for row in pets.get("data", {}).get("pet", [])
                      if str(row.get("id")) == str(pet_id)), None)
        assert owner is not None, "test contour needs owner for sampled pet"
        by_client = await mcp.call_tool("get_medical_cards_by_client_id", {
            "client_id": int(owner), "limit": 1,
            "fields": ["id", "pet_id", "date_create"]})
        latest_invoice = await VetmanagerClient().get("/rest/api/invoice", params={
            "limit": 1, "sort": '[{"property":"invoice_date","direction":"DESC"}]'})
        invoice_rows = latest_invoice.get("data", {}).get("invoice") or []
        assert invoice_rows, "test contour needs an invoice row"
        invoice_day = str(invoice_rows[0]["invoice_date"])[:10]
        year, month = map(int, invoice_day.split("-")[:2])
        by_period = await mcp.call_tool("get_invoice_documents_by_period", {
            "date_from": f"{year:04d}-{month:02d}-01",
            "date_to": f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]}", "limit": 1,
            "fields": ["id", "invoice_id", "price"]})

    for response in (per_pet, by_date, by_client, by_period):
        assert not response.is_error
    pet_rows = per_pet.structured_content["data"]["medicalCards"]
    date_rows = by_date.structured_content["medical_cards"]
    client_rows = by_client.structured_content["medical_cards"]
    period_rows = by_period.structured_content["data"]["invoiceDocument"]
    assert pet_rows and date_rows and client_rows and period_rows
    for rows, allowed in ((pet_rows, {"id", "pet_id", "date_create"}),
                          (date_rows, {"id", "pet_id", "date_create"}),
                          (client_rows, {"id", "pet_id", "date_create"}),
                          (period_rows, {"id", "invoice_id", "price"})):
        assert set(rows[0]) <= allowed | {"_mcp_identifier_conflicts"}
    assert observed and all(method == "GET" and code == 200 for method, code in observed)
    with capsys.disabled():
        print("STAGE444_LIVE upstream=GET/200 body=" + str({
            "pet_rows": len(pet_rows), "date_rows": len(date_rows),
            "client_rows": len(client_rows), "period_rows": len(period_rows),
            "period_total": by_period.structured_content["data"].get("totalCount"),
        }))

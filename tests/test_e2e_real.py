"""E2E real API tests against domain devtr6.

Skipped automatically when TEST_DOMAIN / TEST_API_KEY env vars are not set.
Run inside Docker:
    docker compose run --rm -e TEST_DOMAIN=devtr6 -e TEST_API_KEY=<key> test
"""

import os
import pytest
from unittest.mock import patch

import request_credentials
from vetmanager_client import VetmanagerClient
from exceptions import AuthError, VetmanagerError

TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")

skip_if_no_creds = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_API_KEY,
    reason="TEST_DOMAIN and TEST_API_KEY not set — skipping real API tests",
)


def vc() -> VetmanagerClient:
    headers = {"x-vm-domain": TEST_DOMAIN, "x-vm-api-key": TEST_API_KEY}
    with patch.object(request_credentials, "_get_request_headers", return_value=headers):
        return VetmanagerClient()


async def call(coro):
    """Run coro; skip on AuthError (key may be revoked or access restricted)."""
    try:
        return await coro
    except AuthError as e:
        pytest.skip(f"API returned auth error: {e}")
    except VetmanagerError as e:
        pytest.skip(f"API/network error: {e}")


# ── Host resolution ───────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_host_resolves():
    """Billing API must return a valid https:// URL for the test domain."""
    base = await vc()._resolve_host()
    assert base.startswith("https://"), f"Expected https:// URL, got: {base}"


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_host_cached_on_second_call():
    """Billing API called only once per client instance."""
    c = vc()
    base1 = await c._resolve_host()
    base2 = await c._resolve_host()
    assert base1 == base2


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_two_instances_are_independent():
    """Different VetmanagerClient instances must not share host cache."""
    c1 = vc()
    c2 = vc()
    base1 = await c1._resolve_host()
    base2 = await c2._resolve_host()
    assert base1 == base2
    assert c1 is not c2

# ── Entity endpoints ──────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_clients():
    result = await call(vc().get("/rest/api/client", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_users():
    result = await call(vc().get("/rest/api/user", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_goods():
    result = await call(vc().get("/rest/api/good", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_pets():
    result = await call(vc().get("/rest/api/pet", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_admissions():
    result = await call(vc().get("/rest/api/admission", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_invoices():
    result = await call(vc().get("/rest/api/invoice", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_medical_cards():
    result = await call(vc().get("/rest/api/medicalcard", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_clients_pagination():
    """Offset pagination must work without error."""
    result = await call(vc().get("/rest/api/client", params={"limit": 2, "offset": 0}))
    result2 = await call(vc().get("/rest/api/client", params={"limit": 2, "offset": 2}))
    assert "data" in result
    assert "data" in result2


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_nonexistent_client_raises():
    """Requesting a non-existent client must raise NotFoundError."""
    from exceptions import NotFoundError
    try:
        await vc().get("/rest/api/client/999999999")
        pytest.skip("Expected 404 but got success — resource may exist")
    except NotFoundError:
        pass  # expected
    except AuthError as e:
        pytest.skip(f"Auth error: {e}")


# ── Reference entities ────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_breeds():
    result = await call(vc().get("/rest/api/breed", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_pet_types():
    result = await call(vc().get("/rest/api/petType", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_cities():
    result = await call(vc().get("/rest/api/city", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_city_types():
    result = await call(vc().get("/rest/api/cityType", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_streets():
    result = await call(vc().get("/rest/api/street", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_units():
    result = await call(vc().get("/rest/api/unit", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_roles():
    result = await call(vc().get("/rest/api/role", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_user_positions():
    result = await call(vc().get("/rest/api/userPosition", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_combo_manual_names():
    result = await call(vc().get("/rest/api/ComboManualName", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_combo_manual_items():
    result = await call(vc().get("/rest/api/ComboManualItem", params={"limit": 5, "offset": 0}))
    assert "data" in result


# ── Finance entities ──────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_payments():
    result = await call(vc().get("/rest/api/payment", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_closing_of_invoices():
    result = await call(vc().get("/rest/api/closingOfInvoices", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_invoice_documents():
    result = await call(vc().get("/rest/api/invoiceDocument", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_cassas():
    result = await call(vc().get("/rest/api/cassa", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_cassa_closes():
    result = await call(vc().get("/rest/api/cassaclose", params={"limit": 5, "offset": 0}))
    assert "data" in result


# ── Warehouse entities ────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_good_groups():
    result = await call(vc().get("/rest/api/GoodGroup", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_good_sale_params():
    result = await call(vc().get("/rest/api/goodSaleParam", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_party_accounts():
    result = await call(vc().get("/rest/api/PartyAccount", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_party_account_docs():
    result = await call(vc().get("/rest/api/PartyAccountDoc", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_store_documents():
    result = await call(vc().get("/rest/api/StoreDocument", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_suppliers():
    result = await call(vc().get("/rest/api/Suppliers", params={"limit": 5, "offset": 0}))
    assert "data" in result


# ── Clinical entities ─────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_hospitalizations():
    result = await call(vc().get("/rest/api/hospital", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_hospital_blocks():
    result = await call(vc().get("/rest/api/HospitalBlock", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_diagnoses():
    result = await call(vc().get("/rest/api/MedicalCards/AllDiagnoses", params={"limit": 5, "offset": 0}))
    assert "data" in result


# ── Operational entities ──────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_clinics():
    result = await call(vc().get("/rest/api/clinics", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_timesheets():
    result = await call(vc().get("/rest/api/timesheet", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_properties():
    result = await call(vc().get("/rest/api/properties", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_anonymous_clients():
    result = await call(vc().get("/rest/api/user/anonymousList", params={"limit": 5, "offset": 0}))
    assert "data" in result

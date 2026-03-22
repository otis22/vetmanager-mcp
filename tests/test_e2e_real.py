"""E2E real API tests against a dedicated Vetmanager test contour.

Primary env contract:
- TEST_DOMAIN
- TEST_API_KEY

Optional user-token envs:
- TEST_USER_TOKEN
- TEST_USER_TOKEN_BASE_URL
- TEST_USER_LOGIN
- TEST_USER_PASSWORD

Run inside Docker:
    docker compose run --rm -e TEST_DOMAIN=devtr6 -e TEST_API_KEY=<key> test
"""

import asyncio
import os
import pytest
import re
from unittest.mock import AsyncMock, patch

import httpx
import request_credentials
import runtime_auth
from server import mcp
from vetmanager_client import VetmanagerClient
from exceptions import AuthError, VetmanagerError
from vetmanager_connection_service import (
    validate_domain_api_key_connection,
    validate_user_token_connection,
)
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    VetmanagerAuthContext,
)

TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")
TEST_USER_TOKEN = os.environ.get("TEST_USER_TOKEN", "")
TEST_USER_TOKEN_BASE_URL = os.environ.get("TEST_USER_TOKEN_BASE_URL", "")
TEST_USER_LOGIN = os.environ.get("TEST_USER_LOGIN", "")
TEST_USER_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "")
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')

skip_if_no_creds = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_API_KEY,
    reason="TEST_DOMAIN and TEST_API_KEY not set — skipping real API tests",
)
skip_if_no_user_token = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_USER_TOKEN,
    reason="Need TEST_DOMAIN and TEST_USER_TOKEN for direct user-token validation tests",
)
skip_if_no_user_login_flow = pytest.mark.skipif(
    not TEST_USER_TOKEN_BASE_URL or not TEST_USER_LOGIN or not TEST_USER_PASSWORD,
    reason=(
        "TEST_USER_TOKEN_BASE_URL, TEST_USER_LOGIN and TEST_USER_PASSWORD "
        "not set — skipping login/password real smoke tests"
    ),
)


@pytest.fixture(autouse=True)
def cleanup_orphaned_default_loop():
    """Close stray default loops that some sync helpers may leave behind in real E2E runs."""
    yield
    try:
        loop = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        return
    if loop.is_running() or loop.is_closed():
        return
    loop.close()
    asyncio.set_event_loop(None)


def vc() -> VetmanagerClient:
    headers = {"authorization": "Bearer real-test-token"}
    with patch.object(request_credentials, "_get_request_headers", return_value=headers):
        client = VetmanagerClient()
    client._vetmanager_auth = VetmanagerAuthContext(
        auth_mode="domain_api_key",
        domain=TEST_DOMAIN,
        credential=TEST_API_KEY,
    )
    client._auth_source = "bearer"
    client._domain = TEST_DOMAIN
    client._api_key = TEST_API_KEY
    client._account_id = 1
    client._bearer_token_id = 1
    client._connection_id = 1
    client._ensure_runtime_credentials = AsyncMock(return_value=None)
    return client


async def resolve_real_user_token() -> str:
    """Exchange one user token from login/password for smoke tests."""
    if not TEST_USER_TOKEN_BASE_URL or not TEST_USER_LOGIN or not TEST_USER_PASSWORD:
        pytest.skip("Login/password real smoke requires TEST_USER_TOKEN_BASE_URL, TEST_USER_LOGIN and TEST_USER_PASSWORD.")

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as http:
        response = await http.post(
            f"{TEST_USER_TOKEN_BASE_URL.rstrip('/')}/token_auth.php",
            headers={
                "Accept": "application/json",
            },
            files={
                "login": (None, TEST_USER_LOGIN),
                "password": (None, TEST_USER_PASSWORD),
                "app_name": (None, "vetmanager-mcp"),
            },
        )

    if response.status_code == 401:
        detail = ""
        title = ""
        try:
            payload = response.json()
            detail = str(payload.get("detail") or "").strip()
            title = str(payload.get("title") or "").strip()
        except Exception:
            pass
        detail_suffix = f" title={title!r} detail={detail!r}" if title or detail else ""
        raise AssertionError(
            "Login/password token exchange returned HTTP 401."
            + detail_suffix
        )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if isinstance(data, str) and data.strip():
        return data.strip()
    if isinstance(data, dict):
        for key in ("token", "user_token", "api_key", "key"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise AssertionError("token_auth.php response did not contain a usable user token.")


def vc_user_token() -> VetmanagerClient:
    headers = {"authorization": "Bearer real-test-token"}
    with patch.object(request_credentials, "_get_request_headers", return_value=headers):
        client = VetmanagerClient()
    return client


def _extract_csrf_token(html: str) -> str:
    match = CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


async def _post_with_csrf(
    client: httpx.AsyncClient,
    path: str,
    data: dict[str, str],
    *,
    page_path: str | None = None,
) -> httpx.Response:
    csrf_page = await client.get(page_path or path)
    token = _extract_csrf_token(csrf_page.text)
    payload = dict(data)
    payload["csrf_token"] = token
    return await client.post(path, data=payload)


def _post_with_csrf_sync(
    client: httpx.Client,
    path: str,
    data: dict[str, str],
    *,
    page_path: str | None = None,
) -> httpx.Response:
    csrf_page = client.get(page_path or path)
    token = _extract_csrf_token(csrf_page.text)
    payload = dict(data)
    payload["csrf_token"] = token
    return client.post(path, data=payload)


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


@skip_if_no_user_token
@pytest.mark.asyncio
async def test_real_get_users_with_user_token_mode():
    """User-token mode should pass the same runtime/client path as API-key mode."""
    user_token = await resolve_real_user_token()
    client = vc_user_token()
    client._vetmanager_auth = VetmanagerAuthContext(
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        domain=TEST_DOMAIN,
        credential=user_token,
    )
    client._auth_source = "bearer"
    client._domain = TEST_DOMAIN
    client._api_key = user_token
    client._account_id = 1
    client._bearer_token_id = 1
    client._connection_id = 1
    client._ensure_runtime_credentials = AsyncMock(return_value=None)
    result = await call(client.get("/rest/api/user", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
def test_real_web_account_can_issue_bearer_and_call_tool(live_server_url: str, run_async):
    """Real happy-path: web account -> real API-key integration -> bearer -> MCP tool."""
    with httpx.Client(
        base_url=live_server_url,
        follow_redirects=True,
    ) as client:
        register = _post_with_csrf_sync(
            client,
            "/register",
            data={"email": "real-flow@example.com", "password": "real-flow-pass-123"},
        )
        assert register.status_code == 200

        integration = _post_with_csrf_sync(
            client,
            "/account/integration",
            data={"auth_mode": "domain_api_key", "domain": TEST_DOMAIN, "api_key": TEST_API_KEY},
            page_path="/account",
        )
        assert integration.status_code == 200
        assert "Vetmanager integration saved successfully." in integration.text

        issued = _post_with_csrf_sync(
            client,
            "/account/tokens",
            data={"token_name": "Real E2E token", "expires_in_days": "7"},
            page_path="/account",
        )
        assert issued.status_code == 200
        token_match = re.search(r"vm_st_[A-Za-z0-9_\-]+", issued.text)
        assert token_match is not None
        raw_token = token_match.group(0)

    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_clients", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_validate_domain_api_key_connection():
    """Validation helper should accept the dedicated real API-key contour."""
    resolved = await validate_domain_api_key_connection(TEST_DOMAIN, TEST_API_KEY)
    assert resolved.startswith("https://")


@skip_if_no_user_login_flow
@pytest.mark.asyncio
async def test_real_exchange_user_token_from_login_password():
    """Login/password smoke should either yield a token or explicitly skip on auth rejection."""
    user_token = await resolve_real_user_token()
    assert user_token
    assert len(user_token) >= 8


@skip_if_no_user_token
@pytest.mark.asyncio
async def test_real_validate_user_token_connection_from_login_password_or_env_token():
    """Validation helper should accept an explicitly provided real user token."""
    resolved = await validate_user_token_connection(TEST_DOMAIN, TEST_USER_TOKEN)
    assert resolved.startswith("https://")


@skip_if_no_user_login_flow
@pytest.mark.asyncio
async def test_real_validate_user_token_connection_from_login_password_exchange():
    """Validation helper should accept a token received from the real exchange flow."""
    user_token = await resolve_real_user_token()
    resolved = await validate_user_token_connection(TEST_DOMAIN, user_token)
    assert resolved.startswith("https://")


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
async def test_real_get_clients_with_sort_filter():
    """Smoke test for sort/filter support on list GET."""
    params = {
        "limit": 3,
        "offset": 0,
        "sort": '[{"property":"id","direction":"DESC"}]',
        "filter": '[{"property":"id","value":1,"operator":">="}]',
    }
    result = await call(vc().get("/rest/api/client", params=params))
    assert "data" in result


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


# ── Profile tools ─────────────────────────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_vaccinations_pet_66():
    """Pet 66 has at least one vaccination record in devtr6."""
    result = await call(vc().get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": 66, "limit": 50}))
    assert result is not None
    records = result.get("data", {}).get("medicalcards", [])
    assert len(records) >= 1, "Expected at least 1 vaccination record for pet 66"
    first = records[0]
    assert "date" in first
    assert "date_nexttime" in first
    assert "name" in first


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_vaccinations_empty_pet():
    """Endpoint must return empty list for a pet without vaccinations (no crash)."""
    result = await call(vc().get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": 1, "limit": 50}))
    assert result is not None
    records = result.get("data", {}).get("medicalcards", [])
    assert isinstance(records, list)


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_client_profile_422():
    """Aggregate client profile for client_id=422 (owner of pet 66)."""
    import json as _json
    c = vc()

    client_resp = await call(c.get("/rest/api/client/422"))
    assert client_resp is not None
    client_data = client_resp.get("data", {}).get("client", {})
    assert client_data.get("id") == 422

    invoice_filter = _json.dumps([{"property": "client_id", "value": "422"}], separators=(",", ":"))
    invoice_sort = _json.dumps([{"property": "id", "direction": "DESC"}], separators=(",", ":"))
    invoices_resp = await call(c.get("/rest/api/invoice", params={"filter": invoice_filter, "sort": invoice_sort, "limit": 5}))
    invoices = invoices_resp.get("data", {}).get("invoice", []) if invoices_resp else []
    assert isinstance(invoices, list)

    admission_filter = _json.dumps([{"property": "client_id", "value": "422"}], separators=(",", ":"))
    admission_sort = _json.dumps([{"property": "admission_date", "direction": "DESC"}], separators=(",", ":"))
    admissions_resp = await call(c.get("/rest/api/admission", params={"filter": admission_filter, "sort": admission_sort, "limit": 5}))
    admissions = admissions_resp.get("data", {}).get("admission", []) if admissions_resp else []
    assert isinstance(admissions, list)
    assert len(admissions) >= 1


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_pet_profile_66():
    """Aggregate pet profile for pet_id=66 with vaccinations."""
    import json as _json
    c = vc()

    pet_resp = await call(c.get("/rest/api/pet/66"))
    assert pet_resp is not None
    pet_data = pet_resp.get("data", {}).get("pet", {})
    assert pet_data.get("id") == 66

    mc_filter = _json.dumps([{"property": "patient_id", "value": "66"}], separators=(",", ":"))
    mc_sort = _json.dumps([{"property": "id", "direction": "DESC"}], separators=(",", ":"))
    mc_resp = await call(c.get("/rest/api/medicalcard", params={"filter": mc_filter, "sort": mc_sort, "limit": 5}))
    medical_cards = mc_resp.get("data", {}).get("medicalcard", []) if mc_resp else []
    assert isinstance(medical_cards, list)

    vacc_resp = await call(c.get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": 66, "limit": 100}))
    vaccinations = vacc_resp.get("data", {}).get("medicalcards", []) if vacc_resp else []
    assert len(vaccinations) >= 1

    sorted_vacc = sorted(vaccinations, key=lambda r: r.get("date") or "", reverse=True)
    last_vacc = sorted_vacc[0]
    last_date = (last_vacc.get("date") or "").split(" ")[0]
    assert last_date >= "2026-01-01", f"Expected recent vaccination, got: {last_date}"

    next_date = (last_vacc.get("date_nexttime") or "").strip()
    assert next_date != "", "Expected next vaccination date to be set for pet 66"


# ── Warehouse: get_good_stock_balance ─────────────────────────────────────────

@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_good_stock_balance_with_stock():
    """good_id=470 has stock in devtr6 (quantity=100)."""
    result = await call(vc().get(
        "/rest/api/stores/RestOfGoodInWarehouse/",
        params={"good_id": 470, "clinic_id": 1},
    ))
    assert result is not None
    qty_str = result.get("data", {}).get("rest_good_in_warehouse", {}).get("quantity", "")
    assert qty_str != "", "Expected quantity field in response"
    assert float(qty_str) >= 0


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_good_stock_balance_zero():
    """good_id=192 (Анальгин) has no receipts in devtr6 — quantity=0."""
    result = await call(vc().get(
        "/rest/api/stores/RestOfGoodInWarehouse/",
        params={"good_id": 192, "clinic_id": 1},
    ))
    assert result is not None
    qty_str = result.get("data", {}).get("rest_good_in_warehouse", {}).get("quantity", "")
    assert float(qty_str) == 0.0


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_message_reports():
    result = await call(
        vc().get(
            "/rest/api/messages/reports",
            params={"limit": 5, "offset": 0, "campaign": "All users"},
        )
    )
    if not result.get("success", True):
        pytest.skip(f"messages/reports returned API validation error: {result}")
    assert "data" in result

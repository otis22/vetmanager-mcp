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
import json
import os
import pytest
import re
from unittest.mock import AsyncMock, patch

import httpx
from fastmcp.exceptions import ToolError

import auth.request as auth_request
import runtime_auth
from server import _graceful_shutdown, mcp
from tests.conftest import TEST_ENCRYPTION_KEY
from vetmanager_client import VetmanagerClient
from exceptions import AuthError, VetmanagerError
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_connection_service import (
    save_user_login_password_connection,
    validate_domain_api_key_connection,
    validate_user_token_connection,
)
from vetmanager_auth import (
    DEFAULT_USER_TOKEN_APP_NAME,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    VetmanagerAuthContext,
)

TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")
TEST_USER_TOKEN = os.environ.get("TEST_USER_TOKEN", "")
TEST_USER_TOKEN_BASE_URL = os.environ.get("TEST_USER_TOKEN_BASE_URL", "")
TEST_USER_LOGIN = os.environ.get("TEST_USER_LOGIN", "")
TEST_USER_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "")
RUN_REAL_WEB_TESTS = os.environ.get("RUN_REAL_WEB_TESTS") == "1"
TEST_REPORT_AI_ALLOW_SAVE = os.environ.get("TEST_REPORT_AI_ALLOW_SAVE") == "1"
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
skip_if_real_web_not_enabled = pytest.mark.skipif(
    not RUN_REAL_WEB_TESTS,
    reason="Set RUN_REAL_WEB_TESTS=1 to enable opt-in real web flow tests.",
)
skip_if_not_devtr6 = pytest.mark.skipif(
    "devtr6" not in TEST_DOMAIN,
    reason="Stage 161 contract guard is pinned to devtr6 test contour.",
)

pytestmark = pytest.mark.real_api


def vc() -> VetmanagerClient:
    # Stage 109.1: use canonical factory so private-attr access is centralised
    # in runtime_factories. Renames of VetmanagerClient internals need only
    # one edit instead of three test-file copies.
    from tests.runtime_factories import make_client_with_resolved_runtime
    return make_client_with_resolved_runtime(TEST_DOMAIN, TEST_API_KEY)


def _tool_payload(result) -> dict:
    payload = getattr(result, "structured_content", None)
    assert isinstance(payload, dict)
    return payload


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
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
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


def _phone_digits_from_client(row: dict) -> list[str]:
    digits: list[str] = []
    for key in ("cell_phone", "home_phone", "work_phone"):
        raw = row.get(key)
        if not isinstance(raw, str):
            continue
        value = re.sub(r"\D+", "", raw)
        if len(value) >= 7:
            digits.append(value)
    return digits


@skip_if_no_creds
@skip_if_not_devtr6
@pytest.mark.asyncio
async def test_real_vmlink_personal_account_link_by_phone_smoke():
    clients_payload = await call(
        vc().get(
            "/rest/api/client",
            params={"limit": 100, "offset": 0},
        )
    )
    clients = clients_payload.get("data", {}).get("client", [])
    phones: list[str] = []
    if isinstance(clients, list):
        for row in clients:
            if isinstance(row, dict):
                phones.extend(_phone_digits_from_client(row))
    if not phones:
        pytest.skip("No usable client phone available in devtr6 smoke page.")

    found_payload: dict | None = None
    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        for phone_digits in phones[:20]:
            result = await call(
                mcp.call_tool(
                    "get_personal_account_link_by_phone",
                    {"phone": phone_digits},
                )
            )
            payload = _tool_payload(result)
            data = payload.get("data", {})
            if isinstance(data, dict) and data.get("found") is True:
                found_payload = payload
                break

        missing_result = await call(
            mcp.call_tool(
                "get_personal_account_link_by_phone",
                {"phone": "00000009999999"},
            )
        )

    if found_payload is None:
        pytest.skip("No sampled devtr6 client phone produced a VmLink personal link.")
    found_data = found_payload.get("data", {})
    assert found_payload.get("success") is True
    assert found_data.get("found") is True
    assert isinstance(found_data.get("personal_link"), str)
    assert found_data["personal_link"].startswith("https://")
    assert "/cabinet/" in found_data["personal_link"]

    missing_payload = _tool_payload(missing_result)
    missing_data = missing_payload.get("data", {})
    assert missing_payload.get("success") is True
    assert missing_payload.get("message") == "Client profile not found"
    assert missing_data.get("found") is False
    assert missing_data.get("personal_link") is None


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_report_ai_create_and_bounded_poll_non_polluting():
    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    intent = (
        "MCP smoke Report AI: покажи количество выполненных счетов за май 2026 года. "
        "Без персональных данных. "
        + "Укажи только агрегированное количество, без ФИО, телефонов, email и иных персональных данных. "
        * 12
    )
    assert len(intent) > 1000
    with headers_patch, runtime_patch:
        created = _tool_payload(await call(mcp.call_tool(
            "create_report_ai_job",
            {"intent_text": intent},
        )))

    job = created.get("data", {}).get("job", {})
    job_id = job.get("id")
    assert isinstance(job_id, int)
    assert job.get("status") in {
        "queued",
        "recognizing",
        "building_preview",
        "ready_to_save",
        "saved",
        "failed",
        "rejected",
        "needs_confirmation",
        "existing_report_matched",
    }

    current = job
    for _ in range(6):
        if current.get("status") not in {"queued", "recognizing", "building_preview"}:
            break
        await asyncio.sleep(5)
        headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
        with headers_patch, runtime_patch:
            viewed = _tool_payload(await call(mcp.call_tool(
                "get_report_ai_job",
                {"job_id": job_id},
            )))
        current = viewed.get("data", {}).get("job", {})

    assert current.get("id") == job_id
    if current.get("status") == "ready_to_save" and TEST_REPORT_AI_ALLOW_SAVE:
        title = "MCP smoke report ai count May 2026 2026-06-15"
        headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
        with headers_patch, runtime_patch:
            saved = _tool_payload(await call(mcp.call_tool(
                "save_report_ai_job_as_report",
                {"job_id": job_id, "title": title},
            )))
        assert isinstance(saved.get("data", {}).get("report_id"), int)
    if current.get("status") == "needs_confirmation":
        candidates = current.get("candidates") or []
        if not candidates or not isinstance(candidates[0].get("report_id"), int):
            pytest.skip("Report AI needs_confirmation did not return a usable candidate.")
        report_id = candidates[0]["report_id"]
        headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
        with headers_patch, runtime_patch:
            confirmed = _tool_payload(await call(mcp.call_tool(
                "confirm_report_ai_job_candidate",
                {"job_id": job_id, "report_id": report_id},
            )))
        assert confirmed.get("data", {}).get("report_id") == report_id
        headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
        with headers_patch, runtime_patch:
            data = _tool_payload(await call(mcp.call_tool(
                "get_report_ai_job_data",
                {"job_id": job_id},
            )))
        assert isinstance(data.get("data", {}).get("columns"), list)
        assert isinstance(data.get("data", {}).get("total"), int)
        assert isinstance(data.get("data", {}).get("limited"), bool)


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_report_ai_data_from_existing_saved_fixture_when_available():
    expected_fixture_errors = (
        "HTTP 404",
        "NOT_FOUND",
        "INVALID_TRANSITION",
    )
    for job_id in (2, 4):
        headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
        with headers_patch, runtime_patch:
            try:
                result = _tool_payload(await mcp.call_tool(
                    "get_report_ai_job_data",
                    {"job_id": job_id},
                ))
            except ToolError as exc:
                if not any(marker in str(exc) for marker in expected_fixture_errors):
                    raise
                continue
        data = result.get("data", {})
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            assert isinstance(data.get("columns"), list)
            assert isinstance(data.get("total"), int)
            assert isinstance(data.get("limited"), bool)
            if "csv_export_url" in data:
                assert isinstance(data.get("csv_export_url"), str)
            return

    pytest.skip("No existing saved Report AI fixture is available on this contour.")


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_stage169_invoice_goods_combination_search_smoke():
    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        ordinary_result = _tool_payload(await call(mcp.call_tool(
            "search_invoice_goods",
            {"query": "ggg", "clinic_id": 1, "limit": 20},
        )))
        template_default = _tool_payload(await call(mcp.call_tool(
            "search_invoice_goods",
            {"query": "Тест1", "clinic_id": 1, "limit": 20},
        )))
        template_included = _tool_payload(await call(mcp.call_tool(
            "search_invoice_goods",
            {
                "query": "Тест1",
                "clinic_id": 1,
                "limit": 20,
                "include_template_combinations": True,
            },
        )))

    ordinary_items = ordinary_result.get("data", {}).get("items", [])
    template_default_items = template_default.get("data", {}).get("items", [])
    template_included_items = template_included.get("data", {}).get("items", [])
    assert isinstance(ordinary_items, list)
    assert isinstance(template_default_items, list)
    assert isinstance(template_included_items, list)

    fixture_ordinary = [
        item for item in ordinary_items
        if item.get("is_combination") is True and item.get("combination_tag_id") == 2
    ]
    fixture_template_included = [
        item for item in template_included_items
        if item.get("is_combination") is True and item.get("combination_tag_id") == 6
    ]

    if fixture_ordinary:
        assert fixture_ordinary[0].get("is_template") is False
    if fixture_template_included:
        assert fixture_template_included[0].get("is_template") is True
        assert all(item.get("combination_tag_id") != 6 for item in template_default_items)

    if not fixture_ordinary and not fixture_template_included:
        headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
        with headers_patch, runtime_patch:
            broad = _tool_payload(await call(mcp.call_tool(
                "search_invoice_goods",
                {"query": "", "clinic_id": 1, "limit": 20, "include_template_combinations": True},
            )))
        combo_rows = [
            item for item in broad.get("data", {}).get("items", [])
            if item.get("is_combination") is True
        ]
        if not combo_rows:
            pytest.skip("No GoodsSets combination rows available on this contour.")
        assert isinstance(combo_rows[0].get("combination_tag_id"), int)
        assert combo_rows[0].get("is_template") in {True, False, None}


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_stage169_good_combination_price_smoke():
    tag_id = 2
    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        try:
            combination = _tool_payload(await mcp.call_tool(
                "get_good_combination",
                {"tag_id": tag_id, "clinic_id": 1},
            ))
        except ToolError as exc:
            if "not found" not in str(exc) and "HTTP 404" not in str(exc):
                raise
            pytest.skip("Known good combination fixture tag_id=2 is unavailable.")
        calculated = _tool_payload(await call(mcp.call_tool(
            "calculate_good_combination_price",
            {"tag_id": tag_id, "quantity": 2, "clinic_id": 1},
        )))

    combo = combination.get("data", {}).get("combination", {})
    assert combo.get("id") == tag_id
    assert combo.get("positions") is None or isinstance(combo.get("positions"), list)
    data = calculated.get("data", {})
    assert isinstance(data.get("good"), dict)
    assert "amount" in data["good"]
    assert "action_is_possible" in data


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_users():
    result = await call(vc().get("/rest/api/user", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_user_login_flow
@pytest.mark.asyncio
async def test_real_get_users_with_user_token_mode():
    """User-token mode should pass the same runtime/client path as API-key mode."""
    user_token = await resolve_real_user_token()
    # Stage 109.1: single factory call handles user_token header +
    # app_name automatically via make_vetmanager_auth_context.
    from tests.runtime_factories import make_client_with_resolved_runtime
    client = make_client_with_resolved_runtime(
        TEST_DOMAIN, user_token, auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
    )
    result = await call(client.get("/rest/api/user", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@skip_if_real_web_not_enabled
def test_real_web_account_can_issue_bearer_and_call_tool(live_server_url: str, run_async):
    """Real happy-path: web account -> real API-key integration -> bearer -> MCP tool."""
    with httpx.Client(
        base_url=live_server_url,
        follow_redirects=True,
    ) as client:
        register = _post_with_csrf_sync(
            client,
            "/register",
            data={"email": "real-flow@example.com", "password": "RealFlow-pass-123"},
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
            data={
                "token_name": "Real E2E token",
                "expires_in_days": "7",
                "ip_mask": "*.*.*.*",
                "confirm_wildcard_ip": "1",
            },
            page_path="/account",
        )
        assert issued.status_code == 200
        token_match = re.search(r"vm_st_[A-Za-z0-9_\-]+", issued.text)
        assert token_match is not None
        raw_token = token_match.group(0)

    with patch.object(
        auth_request,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_clients", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content
    run_async(_graceful_shutdown())


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
    resolved = await validate_user_token_connection(
        TEST_DOMAIN,
        TEST_USER_TOKEN,
        app_name=DEFAULT_USER_TOKEN_APP_NAME,
    )
    assert resolved.startswith("https://")


@skip_if_no_user_login_flow
@pytest.mark.asyncio
async def test_real_validate_user_token_connection_from_login_password_exchange():
    """Validation helper should accept a token received from the real exchange flow."""
    user_token = await resolve_real_user_token()
    resolved = await validate_user_token_connection(
        TEST_DOMAIN,
        user_token,
        app_name=DEFAULT_USER_TOKEN_APP_NAME,
    )
    assert resolved.startswith("https://")


@skip_if_no_user_login_flow
@pytest.mark.asyncio
async def test_real_save_user_login_password_connection_uses_real_user_token_contract(sqlite_session_factory_builder, tmp_path):
    """Full service helper should accept real login/password exchange and persist user_token mode."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "real-user-token-save.db")
    async with session_factory() as session:
        connection = await save_user_login_password_connection(
            session,
            account_id=1,
            domain=TEST_DOMAIN,
            login=TEST_USER_LOGIN,
            password=TEST_USER_PASSWORD,
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(type(connection), connection.id)

    assert stored is not None
    credentials = stored.get_credentials(encryption_key=TEST_ENCRYPTION_KEY)
    assert stored.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN
    assert credentials is not None
    assert credentials["domain"] == TEST_DOMAIN
    assert credentials["app_name"] == DEFAULT_USER_TOKEN_APP_NAME
    assert credentials["user_token"]


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
async def test_real_get_medical_cards_by_date_smoke():
    latest = await call(
        vc().get(
            "/rest/api/MedicalCards",
            params={
                "limit": 1,
                "offset": 0,
                "sort": '[{"property":"date_create","direction":"DESC"}]',
            },
        )
    )
    data = latest.get("data", {})
    rows = (
        data.get("medicalCards")
        or data.get("medicalcards")
        or data.get("medicalcard")
        or []
    )
    if not rows:
        pytest.skip("No real medical cards available for date-range smoke.")
    day = str(rows[0].get("date_create", ""))[:10]
    if not day:
        pytest.skip("Latest real medical card has no date_create.")
    clinic_id = rows[0].get("clinic_id")

    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_medical_cards_by_date",
            {"date": day, "limit": 1},
        )

    payload = _tool_payload(result)
    assert payload["date_from"] == day
    assert payload["date_to"] == day
    assert payload["clinic_filter_applied"] is False
    assert payload["total_known"] is True
    assert payload["medical_cards_count"] <= 1
    assert isinstance(payload["medical_cards"], list)

    if clinic_id in (None, ""):
        pytest.skip("Latest real medical card has no clinic_id for branch filter smoke.")
    clinic_id_int = int(clinic_id)

    with headers_patch, runtime_patch:
        clinic_result = await mcp.call_tool(
            "get_medical_cards_by_date",
            {"date": day, "clinic_id": clinic_id_int, "limit": 1},
        )

    clinic_payload = _tool_payload(clinic_result)
    assert clinic_payload["clinic_filter_applied"] is True
    assert clinic_payload["clinic_id"] == clinic_id_int
    assert clinic_payload["total_known"] is True
    assert clinic_payload["medical_cards_count"] <= 1
    for card in clinic_payload["medical_cards"]:
        assert str(card.get("clinic_id")) == str(clinic_id)


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
@skip_if_not_devtr6
@pytest.mark.asyncio
async def test_real_get_client_payment_applications_uses_closing_contract():
    filters = json.dumps([
        {"property": "plus_type_document", "value": "payment", "operator": "="},
    ])
    seed = await call(
        vc().get(
            "/rest/api/closingOfInvoices",
            params={"limit": 1, "offset": 0, "filter": filters},
        )
    )
    seed_rows = seed.get("data", {}).get("closingOfInvoices", [])
    if not seed_rows:
        pytest.skip("devtr6 has no closingOfInvoices payment applications to smoke")
    client_id = int(seed_rows[0]["client_id"])

    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        result = await call(mcp.call_tool(
            "get_client_payment_applications",
            {"client_id": client_id, "limit": 5},
        ))

    data = _tool_payload(result)["data"]
    rows = data["closingOfInvoices"]
    assert data["client_id"] == client_id
    assert rows
    assert all(int(row["client_id"]) == client_id for row in rows)
    assert all(row.get("plus_type_document") == "payment" for row in rows)


@skip_if_no_creds
@pytest.mark.asyncio
async def test_real_get_invoice_documents():
    result = await call(vc().get("/rest/api/invoiceDocument", params={"limit": 5, "offset": 0}))
    assert "data" in result


@skip_if_no_creds
@skip_if_not_devtr6
@pytest.mark.asyncio
async def test_real_get_invoice_documents_by_invoice_id_uses_mcp_contract():
    import json as _json

    for invoice_id in (2, 4):
        headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
        with headers_patch, runtime_patch:
            result = await call(mcp.call_tool(
                "get_invoice_documents",
                {"invoice_id": invoice_id, "limit": 5, "offset": 0},
            ))

        assert result.structured_content is not None
        data = result.structured_content.get("data", {})
        assert isinstance(data, dict), f"unexpected data shape: {type(data).__name__}"
        rows = data.get("invoiceDocument") or data.get("invoiceDocuments") or data
        assert isinstance(rows, list)
        assert rows, f"devtr6 invoice_id={invoice_id} should have invoiceDocument rows"
        assert all(str(row.get("document_id")) == str(invoice_id) for row in rows if isinstance(row, dict))

    c = vc()
    for bad_property in ("invoice_id", "invoiceId", "documentId"):
        bad_filter = _json.dumps(
            [{"property": bad_property, "value": 2, "operator": "="}],
            separators=(",", ":"),
        )
        with pytest.raises(VetmanagerError):
            await c.get("/rest/api/invoiceDocument", params={"filter": bad_filter, "limit": 5, "offset": 0})


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

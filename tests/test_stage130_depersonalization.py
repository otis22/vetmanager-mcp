"""Stage 130.5-130.7 depersonalization sanitizer coverage."""

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import depersonalization
import runtime_auth
import tools
from exceptions import AuthError
from depersonalization import (
    REDACTED_ADDRESS,
    REDACTED_EMAIL,
    REDACTED_NAME,
    REDACTED_PHONE,
    sanitize_text,
    sanitize_tool_result,
)
from server import mcp
from tests.runtime_factories import make_vetmanager_auth_context, patch_runtime_credentials
from token_scopes import SUPPORTED_TOKEN_SCOPES
from vetmanager_client import VetmanagerClient


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch(*, is_depersonalized: bool):
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        is_depersonalized=is_depersonalized,
    )


class _DummySession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return None


def _dummy_session_factory():
    return _DummySession()


def _bearer_context(
    *,
    domain: str = DOMAIN,
    api_key: str = API_KEY,
    account_id: int = 1,
    bearer_token_id: int = 11,
    connection_id: int = 21,
    is_depersonalized: bool = False,
):
    return SimpleNamespace(
        vetmanager_auth=make_vetmanager_auth_context(domain, api_key),
        account_id=account_id,
        bearer_token_id=bearer_token_id,
        connection_id=connection_id,
        scopes=SUPPORTED_TOKEN_SCOPES,
        is_depersonalized=is_depersonalized,
    )


def _patch_runtime_auth_resolution(monkeypatch, resolver, *, token_getter=lambda: "mock-token"):
    monkeypatch.setattr(runtime_auth, "get_bearer_token", token_getter)
    monkeypatch.setattr(runtime_auth, "get_session_factory", lambda: _dummy_session_factory)
    monkeypatch.setattr(runtime_auth, "get_storage_encryption_key", lambda: "test-key")
    monkeypatch.setattr(runtime_auth, "resolve_bearer_auth_context", resolver)


def test_sanitize_tool_result_redacts_structured_fields_recursively():
    payload = {
        "data": {
            "firstName": "Anna",
            "phone": "+7 (916) 123-45-67",
            "email": "anna@example.com",
            "address": "ул. Пушкина, д. 10",
            "owner": {"name": "Иван Иванов"},
            "nested": [{"client_name": "Petr Petrov"}],
            "id": 42,
        }
    }

    sanitized = sanitize_tool_result(payload)

    assert sanitized["data"]["firstName"] == REDACTED_NAME
    assert sanitized["data"]["phone"] == REDACTED_PHONE
    assert sanitized["data"]["email"] == REDACTED_EMAIL
    assert sanitized["data"]["address"] == REDACTED_ADDRESS
    assert sanitized["data"]["owner"]["name"] == REDACTED_NAME
    assert sanitized["data"]["nested"][0]["client_name"] == REDACTED_NAME
    assert sanitized["data"]["id"] == 42


def test_sanitize_tool_result_redacts_vm_phone_and_note_aliases():
    payload = {
        "data": {
            "home_phone": "+7 (916) 111-22-33",
            "work-phone": "+7 (916) 222-33-44",
            "cell_phone": "+7 (916) 333-44-55",
            "owner_phone": "+7 (916) 444-55-66",
            "note": "Владелец Иван Иванов, телефон +7 (916) 555-66-77",
            "deathnote": "Owner John Smith, email owner@example.com",
        }
    }

    sanitized = sanitize_tool_result(payload)

    assert sanitized["data"]["home_phone"] == REDACTED_PHONE
    assert sanitized["data"]["work-phone"] == REDACTED_PHONE
    assert sanitized["data"]["cell_phone"] == REDACTED_PHONE
    assert sanitized["data"]["owner_phone"] == REDACTED_PHONE
    assert REDACTED_NAME in sanitized["data"]["note"]
    assert REDACTED_PHONE in sanitized["data"]["note"]
    assert REDACTED_NAME in sanitized["data"]["deathnote"]
    assert REDACTED_EMAIL in sanitized["data"]["deathnote"]


def test_sanitize_tool_result_scrubs_vm_medical_card_free_text_keys():
    payload = {
        "data": {
            "diagnos": "owner John Smith reported email john@example.com",
            "diagnos_text": "Владелец Иван Иванов просит выписку",
            "diagnos_type_text": "Окончательный диагноз",
            "recomendation": "Позвонить +7 (916) 123-45-67 владельцу",
            "recommendation": "Owner Anna Smith asked for notes",
            "description": "Acute Otitis without owner data",
        }
    }

    sanitized = sanitize_tool_result(payload)

    assert REDACTED_NAME in sanitized["data"]["diagnos"]
    assert REDACTED_EMAIL in sanitized["data"]["diagnos"]
    assert REDACTED_NAME in sanitized["data"]["diagnos_text"]
    assert sanitized["data"]["diagnos_type_text"] == "Окончательный диагноз"
    assert REDACTED_PHONE in sanitized["data"]["recomendation"]
    assert REDACTED_NAME in sanitized["data"]["recommendation"]
    assert sanitized["data"]["description"] == "Acute Otitis without owner data"


def test_sanitize_text_scrubs_only_explicit_patterns():
    text = (
        "Владелец Иван Иванов оставил телефон +7 (916) 123-45-67, "
        "email ivan@example.com. Пациент чувствует себя лучше."
    )

    sanitized = sanitize_text(text)

    assert REDACTED_PHONE in sanitized
    assert REDACTED_EMAIL in sanitized
    assert REDACTED_NAME in sanitized
    assert "Пациент чувствует себя лучше." in sanitized


def test_sanitize_text_scrubs_uppercase_owner_prefixes():
    text = "OWNER JOHN SMITH, ВЛАДЕЛЕЦ ИВАН ИВАНОВ"

    sanitized = sanitize_text(text)

    assert sanitized.count(REDACTED_NAME) == 2
    assert "JOHN SMITH" not in sanitized
    assert "ИВАН ИВАНОВ" not in sanitized


def test_sanitize_text_preserves_bare_full_name_without_pii_signal():
    text = "Пациенту Иван Иванов назначен осмотр"

    assert sanitize_text(text) == text


@pytest.mark.parametrize(
    "clinical_phrase",
    [
        "Acute Otitis",
        "Chronic Bronchitis",
        "Острый Отит",
        "Хронический Гастрит",
        "Средний Отит Уха",
    ],
)
def test_sanitize_text_preserves_clinical_title_case_phrases(clinical_phrase):
    assert sanitize_text(clinical_phrase) == clinical_phrase


def test_sanitize_tool_result_is_idempotent_and_preserves_non_whitelist_text():
    payload = {
        "data": {
            "description": "Owner John Smith, phone +1 (555) 111-22-33",
            "title": "John Smith should stay in title",
            "phone": REDACTED_PHONE,
        }
    }

    once = sanitize_tool_result(payload)
    twice = sanitize_tool_result(once)

    assert once == twice
    assert once["data"]["title"] == "John Smith should stay in title"


@pytest.mark.asyncio
@respx.mock
async def test_mcp_tool_response_is_sanitized_for_depersonalized_token():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "id": 42,
                    "firstName": "Anna",
                    "phone": "+7 (916) 123-45-67",
                    "email": "anna@example.com",
                    "address": "ул. Пушкина, д. 10",
                }
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=True)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_client_by_id", {"client_id": 42})

    assert result.structured_content["data"]["id"] == 42
    assert result.structured_content["data"]["firstName"] == REDACTED_NAME
    assert result.structured_content["data"]["phone"] == REDACTED_PHONE
    assert result.structured_content["data"]["email"] == REDACTED_EMAIL
    assert result.structured_content["data"]["address"] == REDACTED_ADDRESS


@pytest.mark.asyncio
@respx.mock
async def test_non_depersonalized_token_preserves_original_payload():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"id": 42, "firstName": "Anna", "phone": "+7 (916) 123-45-67"}},
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=False)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_client_by_id", {"client_id": 42})

    assert result.structured_content["data"]["firstName"] == "Anna"
    assert result.structured_content["data"]["phone"] == "+7 (916) 123-45-67"


@pytest.mark.asyncio
@respx.mock
async def test_free_text_whitelist_fields_are_scrubbed_for_depersonalized_token():
    billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "id": 42,
                    "description": "Владелец Иван Иванов, email ivan@example.com, телефон +7 (916) 123-45-67.",
                    "title": "Не трогать title",
                }
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=True)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_medical_card_by_id", {"card_id": 42})

    assert REDACTED_NAME in result.structured_content["data"]["description"]
    assert REDACTED_EMAIL in result.structured_content["data"]["description"]
    assert REDACTED_PHONE in result.structured_content["data"]["description"]
    assert result.structured_content["data"]["title"] == "Не трогать title"


@pytest.mark.asyncio
@respx.mock
async def test_depersonalized_get_debtors_redacts_real_phone_fields():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "client": [
                        {
                            "id": 42,
                            "last_name": "Ivanov",
                            "first_name": "Ivan",
                            "middle_name": "Ivanovich",
                            "cell_phone": "+7 (916) 123-45-67",
                            "home_phone": "+7 (916) 222-33-44",
                            "balance": "-50.00",
                            "status": "ACTIVE",
                        }
                    ]
                }
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=True)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_debtors", {})

    debtor = result.structured_content["debtors"][0]
    assert debtor["last_name"] == REDACTED_NAME
    assert debtor["first_name"] == REDACTED_NAME
    assert debtor["middle_name"] == REDACTED_NAME
    assert debtor["cell_phone"] == REDACTED_PHONE
    assert debtor["home_phone"] == REDACTED_PHONE


@pytest.mark.asyncio
@respx.mock
async def test_depersonalized_token_fails_closed_when_sanitizer_errors():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42, "firstName": "Anna"}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=True)
    with (
        headers_patch,
        runtime_patch,
        patch.object(depersonalization, "sanitize_tool_result", side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(ToolError, match="Depersonalization failed.") as exc_info:
            await mcp.call_tool("get_client_by_id", {"client_id": 42})
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_wrapper_fails_closed_before_tool_when_runtime_auth_fails(monkeypatch):
    called = False

    async def resolver(*_args, **_kwargs):
        raise AuthError("revoked token secret-token tenant-42", status_code=401)

    _patch_runtime_auth_resolution(monkeypatch, resolver)

    async def tool_func():
        nonlocal called
        called = True
        return {"data": {"firstName": "Anna"}}

    wrapped = tools._wrap_tool_with_depersonalization(tool_func, tool_name="get_clients")

    with pytest.raises(ToolError) as exc_info:
        await wrapped()

    assert called is False
    assert "secret-token" not in str(exc_info.value)
    assert "tenant-42" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_wrapper_shares_runtime_credentials_with_vetmanager_client(monkeypatch):
    calls: list[str] = []

    async def resolver(bearer_token, *_args, **_kwargs):
        calls.append(bearer_token)
        return _bearer_context(is_depersonalized=False)

    _patch_runtime_auth_resolution(monkeypatch, resolver, token_getter=lambda: "shared-token")

    async def tool_func():
        client = VetmanagerClient()
        await client._ensure_runtime_credentials()
        return {"domain": client._domain}

    wrapped = tools._wrap_tool_with_depersonalization(tool_func, tool_name="get_clients")

    result = await wrapped()

    assert result == {"domain": DOMAIN}
    assert calls == ["shared-token"]


@pytest.mark.asyncio
async def test_runtime_credentials_context_is_isolated_between_concurrent_tools(monkeypatch):
    current_token: ContextVar[str] = ContextVar("stage131_current_token")

    async def resolver(bearer_token, *_args, **_kwargs):
        await asyncio.sleep(0)
        return _bearer_context(
            domain=f"{bearer_token}-clinic",
            api_key=f"{bearer_token}-key",
            bearer_token_id=1 if bearer_token == "a" else 2,
            is_depersonalized=False,
        )

    _patch_runtime_auth_resolution(monkeypatch, resolver, token_getter=current_token.get)

    async def call_with_token(token: str):
        token_marker = current_token.set(token)
        try:
            async def tool_func():
                await asyncio.sleep(0)
                client = VetmanagerClient()
                await client._ensure_runtime_credentials()
                return {"domain": client._domain, "api_key": client._api_key}

            wrapped = tools._wrap_tool_with_depersonalization(tool_func, tool_name="get_clients")
            return await wrapped()
        finally:
            current_token.reset(token_marker)

    result_a, result_b = await asyncio.gather(call_with_token("a"), call_with_token("b"))

    assert result_a == {"domain": "a-clinic", "api_key": "a-key"}
    assert result_b == {"domain": "b-clinic", "api_key": "b-key"}


@pytest.mark.asyncio
async def test_runtime_credentials_context_resets_after_tool_failure(monkeypatch):
    async def resolver(bearer_token, *_args, **_kwargs):
        return _bearer_context(domain=f"{bearer_token}-clinic", is_depersonalized=False)

    _patch_runtime_auth_resolution(monkeypatch, resolver, token_getter=lambda: "first")

    async def failing_tool():
        raise RuntimeError("tool failed")

    wrapped = tools._wrap_tool_with_depersonalization(failing_tool, tool_name="get_clients")

    with pytest.raises(RuntimeError, match="tool failed"):
        await wrapped()

    assert runtime_auth.get_current_runtime_credentials() is None

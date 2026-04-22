"""Stage 130.5-130.7 depersonalization sanitizer coverage."""

from unittest.mock import patch

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import depersonalization
from depersonalization import (
    REDACTED_ADDRESS,
    REDACTED_EMAIL,
    REDACTED_NAME,
    REDACTED_PHONE,
    sanitize_text,
    sanitize_tool_result,
)
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


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
        with pytest.raises(ToolError, match="Depersonalization failed."):
            await mcp.call_tool("get_client_by_id", {"client_id": 42})

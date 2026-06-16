import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import SCOPE_CLIENTS_READ, SCOPE_PETS_READ, required_scope_for_request


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"
PHONE_DIGITS = "79184140259"
LINK = "https://link.vetmanager.ru/cabinet/domain-token/client-token"
GENERIC_ERROR = "Unable to get personal account link from Vetmanager."
NOT_FOUND_MESSAGE = "Client profile not found"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch(*, scopes=(SCOPE_CLIENTS_READ,), is_depersonalized: bool = False):
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        scopes=scopes,
        is_depersonalized=is_depersonalized,
    )


def _structured(result) -> dict:
    return result.structured_content


def _success_payload() -> dict:
    return {
        "success": True,
        "message": "Records Retrieved Successfully",
        "data": {
            "vetmanagerLink": {
                "personal_link": LINK,
                "success": True,
            }
        },
    }


@pytest.mark.asyncio
@respx.mock
async def test_get_personal_account_link_by_phone_normalizes_and_returns_link():
    billing_mock()
    route = respx.get(
        f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/{PHONE_DIGITS}"
    ).mock(return_value=httpx.Response(200, json=_success_payload()))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_personal_account_link_by_phone",
            {"phone": "+7 (918) 414-02-59"},
        )

    payload = _structured(result)
    assert route.call_count == 1
    assert payload["success"] is True
    assert payload["message"] == ""
    assert payload["data"]["found"] is True
    assert payload["data"]["personal_link"] == LINK
    assert payload["data"]["link_is_persistent"] is True
    assert "persistent" in payload["data"]["warning"]


@pytest.mark.asyncio
@respx.mock
async def test_get_personal_account_link_by_phone_not_found_uses_fixed_safe_message():
    billing_mock()
    route = respx.get(
        f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/{PHONE_DIGITS}"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": f"Client profile not found for {PHONE_DIGITS}",
                "data": {"vetmanagerLink": {"success": False}},
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_personal_account_link_by_phone",
            {"phone": PHONE_DIGITS},
        )

    payload = _structured(result)
    assert route.call_count == 1
    assert payload["success"] is True
    assert payload["message"] == NOT_FOUND_MESSAGE
    assert payload["data"] == {
        "found": False,
        "personal_link": None,
        "warning": payload["data"]["warning"],
    }
    assert PHONE_DIGITS not in str(payload)


@pytest.mark.asyncio
@respx.mock
async def test_get_personal_account_link_by_phone_rejects_too_short_before_upstream():
    billing_mock()
    route = respx.get(
        f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/123"
    ).mock(return_value=httpx.Response(200, json=_success_payload()))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool("get_personal_account_link_by_phone", {"phone": "123"})

    assert route.call_count == 0
    assert "at least 7 digits" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_personal_account_link_by_phone_upstream_error_redacts_link_and_phone():
    billing_mock()
    route = respx.get(
        f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/{PHONE_DIGITS}"
    ).mock(
        return_value=httpx.Response(
            500,
            json={
                "message": f"failed for {PHONE_DIGITS}: {LINK}",
                "data": {"details": {"personal_link": LINK}},
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool(
                "get_personal_account_link_by_phone",
                {"phone": PHONE_DIGITS},
            )

    message = str(exc_info.value)
    assert route.call_count == 1
    assert GENERIC_ERROR in message
    assert LINK not in message
    assert PHONE_DIGITS not in message
    assert "/personalAccountLinkByPhone/" not in message


@pytest.mark.asyncio
@respx.mock
async def test_get_personal_account_link_by_phone_timeout_redacts_request_url_and_phone():
    billing_mock()
    route = respx.get(
        f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/{PHONE_DIGITS}"
    ).mock(side_effect=httpx.ReadTimeout("simulated timeout"))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool(
                "get_personal_account_link_by_phone",
                {"phone": PHONE_DIGITS},
            )

    message = str(exc_info.value)
    assert route.call_count >= 1
    assert GENERIC_ERROR in message
    assert PHONE_DIGITS not in message
    assert "/personalAccountLinkByPhone/" not in message


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        {"success": True, "data": {}},
        {"success": False, "message": f"Client profile not found for {PHONE_DIGITS}"},
    ],
)
async def test_get_personal_account_link_by_phone_malformed_or_failed_envelope_is_toolerror(payload):
    billing_mock()
    respx.get(f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/{PHONE_DIGITS}").mock(
        return_value=httpx.Response(200, json=payload)
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool(
                "get_personal_account_link_by_phone",
                {"phone": PHONE_DIGITS},
            )

    assert GENERIC_ERROR in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_personal_account_link_by_phone_preserves_link_for_depersonalized_token():
    billing_mock()
    respx.get(f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/{PHONE_DIGITS}").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )

    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=True)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_personal_account_link_by_phone",
            {"phone": PHONE_DIGITS},
        )

    assert _structured(result)["data"]["personal_link"] == LINK


@pytest.mark.asyncio
@respx.mock
async def test_get_personal_account_link_by_phone_requires_clients_read_before_upstream():
    billing_mock()
    route = respx.get(
        f"{BASE}/rest/api/VmLink/personalAccountLinkByPhone/{PHONE_DIGITS}"
    ).mock(return_value=httpx.Response(200, json=_success_payload()))

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_PETS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool(
                "get_personal_account_link_by_phone",
                {"phone": PHONE_DIGITS},
            )

    assert route.call_count == 0
    assert "clients.read" in str(exc_info.value)


@pytest.mark.asyncio
async def test_stage171_exposes_phone_tool_but_no_client_id_variant():
    tools = {tool.name for tool in await mcp.list_tools()}

    assert "get_personal_account_link_by_phone" in tools
    assert "get_personal_account_link_by_client_id" not in tools


def test_stage171_direct_vmlink_request_scope_maps_to_clients_read():
    assert (
        required_scope_for_request(
            "GET", "/rest/api/VmLink/personalAccountLinkByPhone/79184140259"
        )
        == SCOPE_CLIENTS_READ
    )

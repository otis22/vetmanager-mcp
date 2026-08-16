"""Regression coverage for client and nested-staff output redaction."""

from datetime import date
from decimal import Decimal
from enum import Enum
from unittest.mock import AsyncMock
from uuid import UUID

from fastmcp.exceptions import ToolError
from pydantic import create_model
import pytest

from privacy_utils import redact_sensitive_output_fields, redact_tool_error
from server import mcp
from tests.runtime_factories import make_runtime_credentials, patch_runtime_credentials
from tool_descriptions import PRIVACY_DESCRIPTION_SUFFIXES, SPECIAL_TOOL_DESCRIPTIONS
import tools


_UPSTREAM_CLIENT = {
    "id": 42,
    "last_name": "Иванова",
    "first_name": "Анна",
    "email": "anna@example.test",
    "cell_phone": "+79990000000",
    "passport_series": "1234 567890",
    "custom_agent_field": "must be preserved",
}

_UPSTREAM_STAFF = {
    "id": 7,
    "first_name": "Анна",
    "position_id": 3,
    "email": "anna@example.test",
    "login": "anna.admin",
    "passwd": "0123456789abcdef0123456789abcdef",
    "last_change_pwd_date": "2026-08-01",
    "user_inn": "123456789012",
    "calc_percents": 25,
    "custom_invoice_context": "must be preserved",
}


def _runtime_patch():
    return patch_runtime_credentials(
        "testclinic",
        "test-key-mock",
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _assert_passport_redacted(client: dict) -> None:
    assert "passport_series" not in client
    assert client["id"] == _UPSTREAM_CLIENT["id"]
    assert client["email"] == _UPSTREAM_CLIENT["email"]
    assert client["custom_agent_field"] == _UPSTREAM_CLIENT["custom_agent_field"]


def _assert_staff_credentials_redacted(user: dict) -> None:
    for field in ("passwd", "login", "last_change_pwd_date", "user_inn", "calc_percents"):
        assert field not in user
    assert user["id"] == _UPSTREAM_STAFF["id"]
    assert user["first_name"] == _UPSTREAM_STAFF["first_name"]
    assert user["position_id"] == _UPSTREAM_STAFF["position_id"]
    assert user["email"] == _UPSTREAM_STAFF["email"]
    assert user["custom_invoice_context"] == _UPSTREAM_STAFF["custom_invoice_context"]


_PREEXISTING_DESCRIPTION_FRAGMENTS = {
    "get_users": "List or fetch staff / user records. Use when the user asks to search, browse",
    "get_user_by_id": "Fetch one staff / user record by ID. Use when the user already knows",
    "get_clients": "Use get_client_profile instead for one consolidated owner card",
    "get_client_by_id": "Fetch one client / owner record by ID. Use when the user already knows",
    "get_debtors": "negative-balance filtering",
    "get_client_profile": "recent invoices, recent admissions, and the next scheduled visit",
    "get_pets": "List or fetch pet / patient records. Use when the user asks to search, browse",
    "get_pet_by_id": "Fetch one pet / patient record by ID. Use when the user already knows",
    "get_pet_profile": "recent medical cards, vaccination context",
    "get_admissions": "List or fetch admission / appointment records. Use when the user asks to search, browse",
    "get_admission_by_id": "Fetch one admission / appointment record by ID. Use when the user already knows",
    "get_invoices": "List or fetch invoice / bill records. Use when the user asks to search, browse",
    "get_invoice_by_id": "Fetch one invoice / bill record by ID. Use when the user already knows",
    "get_hospitalizations": "List or fetch hospitalization / inpatient records. Use when the user asks to search, browse",
    "get_hospitalization_by_id": "Fetch one hospitalization / inpatient record by ID. Use when the user already knows",
    "get_cassa_closes": "List or fetch cash register closing records. Use when the user asks",
    "get_cassa_close_by_id": "Fetch one cash register closing record by ID. Use when the user",
}

_PRIVACY_CONTRACT_FRAGMENTS = {
    "get_users": (
        "response is limited to approved staff identity, role/activity, and contact fields",
        "credentials, login, tax, and compensation fields are not returned",
    ),
    "get_user_by_id": (
        "response is limited to approved staff identity, role/activity, and contact fields",
        "credentials, login, tax, and compensation fields are not returned",
    ),
    "get_clients": ("client passport series is not returned",),
    "get_client_by_id": ("client passport series is not returned",),
    "get_debtors": ("client passport series is not returned",),
    "get_client_profile": ("client passport series is not returned",),
    "get_pets": ("returned owner context excludes client passport series",),
    "get_pet_by_id": ("returned owner context excludes client passport series",),
    "get_pet_profile": ("returned owner context excludes client passport series",),
    "get_admissions": ("nested client context excludes client passport series",),
    "get_admission_by_id": ("nested client context excludes client passport series",),
    "get_invoices": (
        "nested client context excludes client passport series",
        "nested staff context excludes credentials, login, tax, and compensation fields",
    ),
    "get_invoice_by_id": (
        "nested client context excludes client passport series",
        "nested staff context excludes credentials, login, tax, and compensation fields",
    ),
    "get_hospitalizations": (
        "nested staff context excludes credentials, login, tax, and compensation fields",
    ),
    "get_hospitalization_by_id": (
        "nested staff context excludes credentials, login, tax, and compensation fields",
    ),
    "get_cassa_closes": (
        "nested staff context excludes credentials, login, tax, and compensation fields",
    ),
    "get_cassa_close_by_id": (
        "nested staff context excludes credentials, login, tax, and compensation fields",
    ),
}


@pytest.mark.asyncio
async def test_privacy_contract_reaches_live_tool_descriptions() -> None:
    tools_by_name = {tool.name: tool for tool in await mcp.list_tools()}

    assert set(_PREEXISTING_DESCRIPTION_FRAGMENTS) == set(PRIVACY_DESCRIPTION_SUFFIXES)
    assert set(_PRIVACY_CONTRACT_FRAGMENTS) == set(PRIVACY_DESCRIPTION_SUFFIXES)
    generated_descriptions = {
        "get_client_by_id",
        "get_users",
        "get_user_by_id",
        "get_pets",
        "get_pet_by_id",
        "get_admissions",
        "get_admission_by_id",
        "get_invoices",
        "get_invoice_by_id",
        "get_hospitalizations",
        "get_hospitalization_by_id",
        "get_cassa_closes",
        "get_cassa_close_by_id",
    }
    assert not generated_descriptions.intersection(SPECIAL_TOOL_DESCRIPTIONS)
    for tool_name, previous_fragment in _PREEXISTING_DESCRIPTION_FRAGMENTS.items():
        description = tools_by_name[tool_name].description
        assert previous_fragment in description
        for privacy_fragment in _PRIVACY_CONTRACT_FRAGMENTS[tool_name]:
            assert privacy_fragment in description

    assert "specific privacy-restricted fields stated in the relevant tool description" in (
        tools_by_name["report_problem"].description
    )


def test_redaction_scopes_generic_staff_fields_to_confirmed_containers() -> None:
    result = redact_sensitive_output_fields(
        {
            "settings": {"login": "integration-login", "calc_percents": 15},
            "doctor": _UPSTREAM_STAFF,
        }
    )

    assert result["settings"] == {"login": "integration-login", "calc_percents": 15}
    _assert_staff_credentials_redacted(result["doctor"])


def test_redaction_handles_tuple_and_json_serializable_pydantic_values() -> None:
    class Status(Enum):
        READY = "ready"

    payload_model = create_model(
        "Payload",
        user=(dict, ...),
        date_value=(date, ...),
        amount=(Decimal, ...),
        request_id=(UUID, ...),
        status=(Status, ...),
    )(
        user=_UPSTREAM_STAFF,
        date_value=date(2026, 8, 16),
        amount=Decimal("12.50"),
        request_id=UUID("12345678-1234-5678-1234-567812345678"),
        status=Status.READY,
    )

    result = redact_sensitive_output_fields((payload_model, {"login": "allowed-setting"}))

    assert isinstance(result, tuple)
    _assert_staff_credentials_redacted(result[0]["user"])
    assert result[0] == {
        "user": result[0]["user"],
        "date_value": "2026-08-16",
        "amount": "12.50",
        "request_id": "12345678-1234-5678-1234-567812345678",
        "status": "ready",
    }
    assert result[1]["login"] == "allowed-setting"


def test_redaction_keeps_unchanged_json_error_string_byte_for_byte() -> None:
    source = '{ "second": 2, "first": 1 }'

    redacted = redact_tool_error(ToolError(source))

    assert redacted.args == (source,)


@pytest.mark.asyncio
async def test_wrapper_preserves_subclass_error_when_skip_hint_bypasses_augmentation(monkeypatch) -> None:
    credentials = make_runtime_credentials("testclinic", "test-key-mock")
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))
    seen = []

    class SpecializedToolError(ToolError):
        def __init__(self, message, marker):
            super().__init__(message)
            self.marker = marker

    original = SpecializedToolError("upstream failed", marker="keep")

    def skip_hint(exc):
        seen.append(exc)
        return True

    monkeypatch.setattr(tools, "should_skip_report_hint", skip_hint)

    async def failing_tool():
        raise original

    wrapped = tools._wrap_tool_with_depersonalization(failing_tool, tool_name="get_invoices")
    with pytest.raises(SpecializedToolError) as exc_info:
        await wrapped()

    assert exc_info.value is original
    assert exc_info.value.marker == "keep"
    assert seen == [original]


@pytest.mark.asyncio
async def test_wrapper_redacts_structured_tool_error_before_augmentation(monkeypatch) -> None:
    credentials = make_runtime_credentials("testclinic", "test-key-mock")
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    async def preserve_sanitized_error(*_args):
        return _args[-1]

    monkeypatch.setattr(tools, "augment_tool_error", preserve_sanitized_error)

    async def failing_tool():
        raise ToolError({"data": {"doctor": _UPSTREAM_STAFF}})

    wrapped = tools._wrap_tool_with_depersonalization(failing_tool, tool_name="get_invoices")
    with pytest.raises(ToolError) as exc_info:
        await wrapped()

    payload = exc_info.value.args[0]
    _assert_staff_credentials_redacted(payload["data"]["doctor"])


@pytest.mark.asyncio
async def test_get_clients_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_list(*args, **kwargs):
        return {"success": True, "data": {"client": [_UPSTREAM_CLIENT], "totalCount": 1}}

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_clients", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["client"][0])


@pytest.mark.asyncio
async def test_get_clients_name_search_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_list(*args, **kwargs):
        return {"success": True, "data": {"client": [_UPSTREAM_CLIENT], "totalCount": 1}}

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_clients", {"name": "Иванова"})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["client"][0])


@pytest.mark.asyncio
async def test_get_client_by_id_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {"success": True, "data": _UPSTREAM_CLIENT}

    monkeypatch.setattr(client_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_client_by_id", {"client_id": 42})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"])


@pytest.mark.asyncio
async def test_get_debtors_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "client": [{**_UPSTREAM_CLIENT, "balance": "-100.00"}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_debtors", {})

    payload = result.structured_content or {}
    assert "passport_series" not in payload["debtors"][0]
    assert payload["debtors"][0]["id"] == _UPSTREAM_CLIENT["id"]


@pytest.mark.asyncio
async def test_get_client_profile_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_fetch_client_profile(*args, **kwargs):
        return {"client": _UPSTREAM_CLIENT, "invoices": [], "admissions": []}

    async def fake_instrument_call(*args, **kwargs):
        return await args[2]()

    monkeypatch.setattr(client_module, "_fetch_client_profile", fake_fetch_client_profile)
    monkeypatch.setattr(client_module, "_instrument_call", fake_instrument_call)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_client_profile", {"client_id": 42})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["client"])


@pytest.mark.asyncio
async def test_get_pet_profile_redacts_owner_passport_series(monkeypatch):
    import tools.pet as pet_module

    async def fake_fetch_pet_profile(*args, **kwargs):
        return {"pet": {"id": 3}, "owner": _UPSTREAM_CLIENT}

    async def fake_instrument_call(*args, **kwargs):
        return await args[2]()

    monkeypatch.setattr(pet_module, "_fetch_pet_profile", fake_fetch_pet_profile)
    monkeypatch.setattr(pet_module, "_instrument_call", fake_instrument_call)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_pet_profile", {"pet_id": 3})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["owner"])


@pytest.mark.asyncio
async def test_get_pets_redacts_nested_owner_passport_series(monkeypatch):
    import tools.pet as pet_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {"pet": [{"id": 3, "owner": _UPSTREAM_CLIENT}], "totalCount": 1},
        }

    monkeypatch.setattr(pet_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_pets", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["pet"][0]["owner"])


@pytest.mark.asyncio
async def test_get_pet_by_id_redacts_nested_owner_passport_series(monkeypatch):
    import tools.pet as pet_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {"success": True, "data": {"id": 3, "owner": _UPSTREAM_CLIENT}}

    monkeypatch.setattr(pet_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_pet_by_id", {"pet_id": 3})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["owner"])


@pytest.mark.asyncio
async def test_get_admissions_redacts_nested_client_passport_series(monkeypatch):
    import tools.admission as admission_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "admission": [{"id": 4, "client": _UPSTREAM_CLIENT}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(admission_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_admissions", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["admission"][0]["client"])


@pytest.mark.asyncio
async def test_get_admission_by_id_redacts_nested_client_passport_series(monkeypatch):
    import tools.admission as admission_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {"success": True, "data": {"id": 4, "client": _UPSTREAM_CLIENT}}

    monkeypatch.setattr(admission_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_admission_by_id", {"admission_id": 4})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["client"])


@pytest.mark.asyncio
async def test_get_invoices_redacts_nested_client_passport_series(monkeypatch):
    import tools.invoice as invoice_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {"invoice": [{"id": 5, "client": _UPSTREAM_CLIENT}], "totalCount": 1},
        }

    monkeypatch.setattr(invoice_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_invoices", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["invoice"][0]["client"])


@pytest.mark.asyncio
async def test_get_invoices_redacts_nested_doctor_credentials(monkeypatch):
    import tools.invoice as invoice_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {"invoice": [{"id": 5, "doctor": _UPSTREAM_STAFF}], "totalCount": 1},
        }

    monkeypatch.setattr(invoice_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_invoices", {})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["invoice"][0]["doctor"])


@pytest.mark.asyncio
async def test_get_invoice_by_id_redacts_nested_client_and_staff(monkeypatch):
    import tools.invoice as invoice_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {
            "success": True,
            "data": {"id": 5, "client": _UPSTREAM_CLIENT, "doctor": _UPSTREAM_STAFF},
        }

    monkeypatch.setattr(invoice_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_invoice_by_id", {"invoice_id": 5})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["client"])
    _assert_staff_credentials_redacted(payload["data"]["doctor"])


@pytest.mark.asyncio
async def test_get_hospitalizations_redacts_nested_doctor_credentials(monkeypatch):
    import tools.clinical as clinical_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "hospital": [{"id": 6, "doctor_data": _UPSTREAM_STAFF}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(clinical_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_hospitalizations", {})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["hospital"][0]["doctor_data"])


@pytest.mark.asyncio
async def test_get_hospitalization_by_id_redacts_nested_doctor_credentials(monkeypatch):
    import tools.clinical as clinical_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {"success": True, "data": {"id": 6, "doctor_data": _UPSTREAM_STAFF}}

    monkeypatch.setattr(clinical_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_hospitalization_by_id", {"hospital_id": 6})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["doctor_data"])


@pytest.mark.asyncio
async def test_get_cassa_closes_redacts_nested_closed_user_credentials(monkeypatch):
    import tools.finance as finance_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "cassaclose": [{"id": 8, "closedUser": _UPSTREAM_STAFF}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(finance_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_cassa_closes", {})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["cassaclose"][0]["closedUser"])


@pytest.mark.asyncio
async def test_get_cassa_close_by_id_redacts_nested_closed_user_credentials(monkeypatch):
    import tools.finance as finance_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {"success": True, "data": {"id": 8, "closedUser": _UPSTREAM_STAFF}}

    monkeypatch.setattr(finance_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_cassa_close_by_id", {"close_id": 8})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["closedUser"])

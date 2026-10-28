"""Stage 441: exported guidance and the medical-card compatibility boundary."""

import pytest
import re
from fastmcp import Client
from jsonschema import Draft202012Validator

from first_request_examples import FIRST_REQUEST_EXAMPLES
from placeholder_resolution_guidance import AGENT_RESOLUTION_GUIDANCE
from prompts import get_report_ai_prompt_helper_text
from server import mcp
from depersonalization import REDACTED_PHONE, sanitize_tool_result
from report_row_types import normalize_report_rows
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.parametrize("fragment", [
    "зерно", "роль колонки", "сумма оплат, ₽", "при уточнении", "После save/confirm",
    "Лабораторные отчёты", "взятия пробы", "историей исправлений", "оплачено",
    "accepted", "посещение", "аванс", "возврат", "дату платежа",
    "партии", "исторический остаток", "дата следующей вакцинации", "владелец на дату",
    "складской остаток — количество", "балансовый остаток — деньги",
])
def test_rendered_helper_contains_business_invariant(fragment):
    _assert_fragments(get_report_ai_prompt_helper_text(), (fragment,))


def _assert_fragments(text, fragments):
    assert all(fragment.casefold() in text.casefold() for fragment in fragments)


@pytest.mark.parametrize("fragments", [
    ("зерно", "роль колонки", "при уточнении", "После save/confirm"),
    ("Лабораторные отчёты", "взятия пробы", "историей исправлений", "оплачено"),
    ("accepted", "посещение", "аванс", "возврат", "дату платежа"),
    ("партии", "исторический остаток", "дата следующей вакцинации", "владелец на дату"),
    ("складской остаток — количество", "балансовый остаток — деньги"),
])
def test_each_helper_block_guard_goes_red_when_text_removed(fragments):
    text = get_report_ai_prompt_helper_text()
    _assert_fragments(text, fragments)
    with pytest.raises(AssertionError):
        _assert_fragments(re.sub(re.escape(fragments[0]), "", text, flags=re.IGNORECASE), fragments)


@pytest.mark.asyncio
async def test_helper_tool_returns_new_sections():
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1,
    )
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_prompt_helper", {})
    body = str(result.structured_content)
    assert "Лабораторные отчёты" in body
    assert "После save/confirm" in body


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,fragments", [
    ("get_admissions", ("accepted", "посещение", "оплата")),
    ("get_payments", ("возврат", "аванс", "дату платежа")),
    ("get_good_stock_balance", ("текущий", "партия", "на дату")),
])
async def test_exported_direct_tool_semantics(tool, fragments):
    exported = {t.name: t.to_mcp_tool() for t in await mcp.list_tools()}
    description = exported[tool].description.casefold()
    _assert_fragments(description, fragments)
    with pytest.raises(AssertionError):
        _assert_fragments(description.replace(fragments[0], ""), fragments)


def test_first_request_examples_have_criteria():
    text = " ".join(answer for _, answer in FIRST_REQUEST_EXAMPLES).casefold()
    assert "по расписанию" in text
    assert "accepted" in text
    assert "отрицательн" in text
    assert "последнего визита" in text


def test_placeholder_guidance_limits_inference():
    text = AGENT_RESOLUTION_GUIDANCE.casefold()
    assert all(fragment in text for fragment in ("связывает строки", "не доказывает роль", "визит"))


@pytest.mark.asyncio
async def test_revenue_default_is_consistent_across_entry_points():
    helper = get_report_ai_prompt_helper_text().casefold()
    description = next(t.to_mcp_tool().description for t in await mcp.list_tools()
                       if t.name == "get_revenue_summary").casefold()
    assert "дефолт исполненных счетов" in helper
    assert 'plain "выручка" defaults to executed invoices' in helper
    assert "'invoiced', the default" in description


@pytest.mark.asyncio
async def test_medical_card_alias_schema():
    exported = {t.name: t.to_mcp_tool() for t in await mcp.list_tools()}
    tool = exported["get_medical_card_by_id"]
    props = tool.inputSchema["properties"]
    assert {"id", "card_id"} <= props.keys()
    assert not {"id", "card_id"} & set(tool.inputSchema.get("required", []))
    assert "ровно один" in tool.description.casefold()
    assert "canonical" in str(props["card_id"]).casefold()
    assert "deprecated" in str(props["id"]).casefold()
    update = exported["update_medical_card"].inputSchema["properties"]
    assert "card_id" in update and "id" not in update
    Draft202012Validator.check_schema(tool.inputSchema)
    async with Client(mcp) as client:
        listed = {item.name: item for item in await client.list_tools()}
        assert "get_medical_card_by_id" in listed
        assert {"id", "card_id"} <= listed["get_medical_card_by_id"].inputSchema["properties"].keys()


@pytest.mark.asyncio
async def test_other_by_id_schema_names_entity_id():
    exported = {t.name: t.to_mcp_tool().inputSchema for t in await mcp.list_tools()}
    _assert_by_id_inventory(exported)
    from copy import deepcopy
    missing_param = deepcopy(exported)
    del missing_param["get_invoice_by_id"]["properties"]["invoice_id"]
    with pytest.raises(AssertionError):
        _assert_by_id_inventory(missing_param)
    missing_description = deepcopy(exported)
    del missing_description["get_invoice_by_id"]["properties"]["invoice_id"]["description"]
    with pytest.raises(AssertionError):
        _assert_by_id_inventory(missing_description)


def _assert_by_id_inventory(exported):
    expected = {
        "client": ("client_id", "client"), "pet": ("pet_id", "pet"),
        "admission": ("admission_id", "admission"), "invoice": ("invoice_id", "invoice"),
        "good": ("good_id", "good"), "user": ("doctor_id", "user"),
        "breed": ("breed_id", "breed"), "pet_type": ("pet_type_id", "animal type"),
        "city": ("city_id", "city"), "street": ("street_id", "street"),
        "unit": ("unit_id", "unit"), "role": ("role_id", "role"),
        "user_position": ("position_id", "position"),
        "combo_manual_name": ("name_id", "catalog name"),
        "combo_manual_item": ("item_id", "catalog item"),
        "payment": ("payment_id", "payment"),
        "closing_of_invoice": ("closing_id", "closing record"),
        "invoice_document": ("doc_id", "invoice document"),
        "cassa": ("cassa_id", "cash register"),
        "cassa_close": ("close_id", "closing record"),
        "good_group": ("group_id", "group"),
        "good_sale_param": ("param_id", "sale parameter"),
        "party_account": ("party_id", "party account"),
        "party_account_doc": ("doc_id", "document"),
        "store_document": ("doc_id", "store document"),
        "supplier": ("supplier_id", "supplier"),
        "hospitalization": ("hospital_id", "hospitalization record"),
        "hospital_block": ("block_id", "hospital block"),
        "clinic": ("clinic_id", "clinic"),
        "timesheet": ("timesheet_id", "timesheet entry"),
    }
    actual = {name.removeprefix("get_").removesuffix("_by_id")
              for name in exported if name.endswith("_by_id") and name != "get_medical_card_by_id"}
    assert actual == expected.keys()
    for entity, (identifier, label) in expected.items():
        props = exported[f"get_{entity}_by_id"]["properties"]
        assert identifier in props, entity
        assert f"id of the {label}" in props[identifier].get("description", "").casefold(), entity


@pytest.mark.asyncio
async def test_medical_card_alias_calls_and_rejects_before_upstream(monkeypatch):
    import tools.medical_card as module

    calls = []

    async def fake_get(endpoint, card_id):
        calls.append((endpoint, card_id))
        return {"success": True, "card_id": card_id}

    monkeypatch.setattr(module, "crud_get_by_id", fake_get)
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1,
    )
    with headers, runtime:
        for args in ({"id": 42}, {"card_id": 42}, {"card_id": "42"}):
            result = await mcp.call_tool("get_medical_card_by_id", args)
            assert result.structured_content["card_id"] == 42
        assert len(calls) == 3
        for args, message in (({}, "ровно один"),
                              ({"id": 42, "card_id": 43}, "ровно один"),
                              ({"id": -1}, "positive integer"),
                              ({"id": "bad"}, "validation"),
                              ({"id": True}, "integer"),
                              ({"card_id": 42.0}, "integer")):
            with pytest.raises(Exception, match=message):
                await mcp.call_tool("get_medical_card_by_id", args)
    assert len(calls) == 3


@pytest.mark.parametrize("column,value,expected", [
    ("Остаток на складе", "12.0000000000", 12),
    ("Количество (остаток)", "12.0000000000", 12),
    ("Остаток баланса клиента", "873.0000000000", 873),
    ("Денежный остаток, ₽", "873.0000000000", 873),
    ("Остаток", "873.0000000000", 873),
])
def test_balance_full_privacy_and_normalization_path(column, value, expected):
    payload = {"data": {"columns": [column, "Телефон", "Сумма", "Примечание"],
                        "rows": [{column: value, "Телефон": "+7 (999) 123-45-67",
                                  "Сумма": "8.9161234567",
                                  "Примечание": "тел. +7 (999) 123-45-67"}]}}
    cleaned = sanitize_tool_result(payload, report_mode=True, tool_name="get_report_ai_job_data")
    row = normalize_report_rows(cleaned)["data"]["rows"][0]
    assert row[column] == expected
    assert REDACTED_PHONE in row["Телефон"]
    assert REDACTED_PHONE in row["Сумма"]
    assert REDACTED_PHONE in row["Примечание"]


def test_balance_guard_detects_removal_of_money_label(monkeypatch):
    import report_row_types as row_types

    monkeypatch.setattr(row_types, "MONEY_COLUMN_NAMES",
                        row_types.MONEY_COLUMN_NAMES - {"остаток"})
    payload = {"data": {"columns": ["Остаток на складе"],
                        "rows": [{"Остаток на складе": "12.0000000000"}]}}
    damaged = sanitize_tool_result(payload, report_mode=True, tool_name="get_report_ai_job_data")
    assert REDACTED_PHONE in damaged["data"]["rows"][0]["Остаток на складе"]

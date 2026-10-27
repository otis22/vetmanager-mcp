"""Этап 396: матрица типов только для строк Report AI."""

import pytest

from server import mcp
from depersonalization import REDACTED_PHONE
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.asyncio
@pytest.mark.parametrize("depersonalized", [False, True])
async def test_registered_report_rows_have_safe_types_after_privacy(monkeypatch, depersonalized):
    import tools.report_ai as report_module

    payload = {"success": True, "data": {
        "columns": ["Сумма", "Баланс", "Количество", "Артикул", "Код товара",
                    "client_id", "Телефон", "Клиент", "Примечание", "Неизвестно"],
        "rows": [{"Сумма": "246800.0000000000", "Баланс": "1.25",
                  "Количество": "7", "Артикул": "007", "Код товара": "0012",
                  "client_id": "00042", "Телефон": "007", "Клиент": "Иванова Мария",
                  "Примечание": "", "Неизвестно": None},
                 {"Сумма": "0.123456789012345678901", "Баланс": "",
                  "Количество": None, "Артикул": "", "Код товара": "007"}],
        "recognized": {"preview_example_row": {"Сумма": "246800.0000000000"}},
        "total": 2,
    }}

    async def fake_call(*args, **kwargs):
        return payload

    monkeypatch.setattr(report_module, "_call_vm", fake_call)
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1, is_depersonalized=depersonalized,
    )
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job_data", {"job_id": 396})
    data = result.structured_content["data"]
    row = data["rows"][0]
    if depersonalized:
        assert row["Сумма"] == 246800
    else:
        assert row["Сумма"] == 246800 and isinstance(row["Сумма"], int)
    assert row["Баланс"] == 1.25 and isinstance(row["Баланс"], float)
    assert row["Количество"] == 7 and isinstance(row["Количество"], int)
    assert row["Артикул"] == "007"
    assert row["Код товара"] == "0012"
    assert row["client_id"] == "00042"
    assert row["Телефон"] == (REDACTED_PHONE if depersonalized else "007")
    assert row["Примечание"] is None and row["Неизвестно"] is None
    if not depersonalized:
        assert data["rows"][1]["Сумма"] == "0.123456789012345678901"
    assert data["rows"][1]["Баланс"] is None
    assert data["rows"][1]["Артикул"] is None
    preview = data["recognized"]["preview_example_row"]["Сумма"]
    assert isinstance(preview, str)
    assert preview == ("246800.[redacted-phone]" if depersonalized else "246800.0000000000")
    assert data["total"] == 2
    if depersonalized:
        assert row["Клиент"] != "Иванова Мария"
    else:
        assert row["Клиент"] == "Иванова Мария"


def test_column_metadata_controls_conversion_without_value_inference():
    from report_row_types import normalize_report_rows

    data = {"data": {"columns": [
        {"name": "Число", "type": "decimal"},
        {"name": "Код", "type": "decimal"},
        {"name": "Сумма", "type": "string"},
        "Неизвестно"], "rows": [{"Число": "12.50", "Код": "007",
                              "Сумма": "15", "Неизвестно": "42"}]}}
    row = normalize_report_rows(data)["data"]["rows"][0]
    assert row == {"Число": 12.5, "Код": "007", "Сумма": "15", "Неизвестно": "42"}
    named = {"data": {"columns": ["Общая сумма", "Количество телефонов"],
                      "rows": [{"Общая сумма": "12.50", "Количество телефонов": "007"}]}}
    assert normalize_report_rows(named)["data"]["rows"][0] == {
        "Общая сумма": 12.5, "Количество телефонов": "007",
    }
    for variants in (({"name": "Сумма", "type": "decimal"},
                      {"name": "Сумма", "type": "string"}),
                     ({"name": "Сумма", "type": "string"},
                      {"name": "Сумма", "type": "decimal"})):
        duplicate = {"data": {"columns": list(variants), "rows": [{"Сумма": "007"}]}}
        assert normalize_report_rows(duplicate)["data"]["rows"][0]["Сумма"] == "007"
    camel = {"data": {"columns": [{"name": "clientId", "type": "integer"}],
                      "rows": [{"clientId": "007"}]}}
    assert normalize_report_rows(camel)["data"]["rows"][0]["clientId"] == "007"
    russian_id = {"data": {"columns": [{"name": "КлиентИД", "type": "integer"}],
                           "rows": [{"КлиентИД": "007"}]}}
    assert normalize_report_rows(russian_id)["data"]["rows"][0]["КлиентИД"] == "007"
    for name in ("ID Клиента", "id_client", "client_id_number", "EAN", "GTIN"):
        protected = {"data": {"columns": [{"name": name, "type": "integer"}],
                              "rows": [{name: "007"}]}}
        assert normalize_report_rows(protected)["data"]["rows"][0][name] == "007"
    for invalid in (None, ""):
        for columns in (({"name": "Сумма", "type": "decimal"},
                         {"name": "Сумма", "type": invalid}),
                        ({"name": "Сумма", "type": invalid},
                         {"name": "Сумма", "type": "decimal"})):
            malformed = {"data": {"columns": list(columns), "rows": [{"Сумма": "007"}]}}
            assert normalize_report_rows(malformed)["data"]["rows"][0]["Сумма"] == "007"


def test_missing_metadata_and_json_number_edges():
    from report_row_types import normalize_report_rows

    source = {"data": {"rows": [{"Сумма": "42", "Пусто": ""}]}}
    assert normalize_report_rows(source)["data"]["rows"] == [{"Сумма": "42", "Пусто": None}]
    values = ["999999999999999999999999999999", "9007199254740991",
              "9007199254740993", "1e3", "1e5000", "-0", "NaN",
              "1.234567890123456789", "0.1"]
    data = {"data": {"columns": ["Сумма"], "rows": [{"Сумма": v} for v in values]}}
    got = [row["Сумма"] for row in normalize_report_rows(data)["data"]["rows"]]
    assert got == ["999999999999999999999999999999", 9007199254740991,
                   "9007199254740993", 1000, "1e5000", "-0", "NaN",
                   "1.234567890123456789", 0.1]


def test_privacy_layer_keeps_phone_in_amount_column_masked():
    from depersonalization import sanitize_report_cell

    assert REDACTED_PHONE in sanitize_report_cell("Сумма", "8.9161234567")

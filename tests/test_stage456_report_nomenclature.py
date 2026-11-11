"""Synthetic Report AI matrix from the owner-approved stage 456 examples."""

import csv
import io
import asyncio
import socket
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
import uvicorn
from fastmcp import FastMCP

from depersonalization import REDACTED_NAME, REDACTED_PHONE, sanitize_report_cell, sanitize_tool_result
import report_export
from report_row_types import normalize_report_rows
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from token_scopes import SCOPE_ANALYTICS_READ
import tools.report_ai as report_ai
from tools import _ToolRegistrationProxy
from tests.runtime_factories import patch_runtime_credentials


COMBINATIONS = (
    "АСТЕРИОНОМ DHPPi LR (соб) вакцинация",
    "ИСПОЛЬЗОВАНИЕ Ш РМ НА ПРИЕМЕ",
    "Мелоксиветом OR 0,2 для кошек лечение",
    "Мелоксиветом OR 1,0 для собак лечение",
    "ОБРАБОТКА ОТ ЭКТОПАРАЗИТОВ (СЕЛАФОРТ)",
    "РЕНТГЕН СЕРИЯ СНИМКОВ (НЕОГРАНИЧЕННОЕ КОЛИЧЕСТВО) С ОПИСАНИЕМ",
    "СТАЦИОНАРНЫЕ РМ использование",
    "ТЕСТ-ЭКСПРЕСС НА ПАНЛЕЙКОПЕНИЮ AГ",
    "ФИКС ОВГ КОШКИ (полостная)",
)
POSITIONS = (
    "Анестезия II категории сложности",
    "Анестезия IV категории сложности",
    "Катетер ЦВК ТРЕХКАНАЛЬНЫЙ",
    "ХН Шапочка Шарлотта",
)
COLUMNS = ("Тип", "Наименование", "Количество", "Сумма", "Телефон", "ФИО")
PHONE = "+7 (999) 123-45-67"
FIO = "Иванов Пётр Сергеевич"


def _source_rows():
    return [
        dict(zip(COLUMNS, (
            "комбинация" if index < 9 else "позиция",
            name, str(index + 1), f"{(index + 1) * 100}.00",
            PHONE, FIO,
        )))
        for index, name in enumerate(COMBINATIONS + POSITIONS)
    ]


def test_complete_report_rows_preserve_nomenclature_and_aggregates():
    source = {"data": {"columns": list(COLUMNS), "rows": _source_rows(),
                       "total": 13, "limited": False}}
    cleaned = sanitize_tool_result(
        source, report_mode=True, tool_name="get_report_ai_job_data"
    )
    actual = normalize_report_rows(cleaned)["data"]
    assert actual["columns"] == list(COLUMNS)
    assert actual["total"] == 13 and actual["limited"] is False
    assert len(actual["rows"]) == 13
    expected = _source_rows()
    for index, row in enumerate(expected):
        row["Количество"] = index + 1
        row["Сумма"] = (index + 1) * 100
    for row in expected:
        row["Телефон"] = REDACTED_PHONE
        row["ФИО"] = REDACTED_NAME
    assert actual["rows"] == expected


def test_complete_csv_preserves_nomenclature_and_masks_contact(tmp_path, monkeypatch):
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(COLUMNS)
    for source_row in _source_rows():
        writer.writerow([source_row[column] for column in COLUMNS])
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-456-synthetic-test-secret")
    report_export.reset_link_key_cache()
    owner = report_export.owner_segment(domain="synthetic", subject_type="service_bearer", subject_id=456)
    filename = report_export.new_export_filename(report_file_id=456)
    _url, row_count, column_count = report_export.store_export_stream(
        raw=io.BytesIO(buffer.getvalue().encode()), delimiter=";", depersonalize=True,
        owner=owner, filename=filename, subject_type="service_bearer", subject_id=456,
        download_name="synthetic-456.csv",
    )
    output = (tmp_path / owner / f"{report_export.file_segment(owner, filename)}.csv").read_text(encoding="utf-8")
    rows = list(csv.reader(io.StringIO(output.lstrip("\ufeff")), delimiter=";"))
    assert (row_count, column_count) == (13, len(COLUMNS))
    assert rows[0] == list(COLUMNS)
    assert len(rows) == 14
    expected = [[row[column] for column in COLUMNS] for row in _source_rows()]
    for row in expected:
        row[4:] = [REDACTED_PHONE, REDACTED_NAME]
    assert rows[1:] == expected


def test_value_level_privacy_in_neutral_and_nomenclature_columns():
    synthetic_names = (
        "Иванов Пётр Сергеевич",
        "ИВАНОВ ПЁТР СЕРГЕЕВИЧ",
        "Иванов И. И.",
        "Иванов ИИ",
        "Ivanov IV",
        "ПЕТРОВ АС",
        "Ivanov Petr Sergeevich",
        "Петров-Водкин Пётр Сергеевич",
        "Шапочка И. И.",
        "Рентген В. К.",
        "Шапочка Иван",
        "Шапочка Иван Сергеевич",
        "Анестезия И. И.",
        "Шапочка Джон Смит",
        "Рентген Джон Смит",
        "РЕНТГЕН Джон Смит",
        "Шапочка ДЖОН СМИТ",
        "Обработка И. И.",
        "Петрова НА",
        "Иванов РМ",
        "Сидоров ОТ",
    )
    for value in synthetic_names + (PHONE,):
        for column in ("Значение", "Наименование"):
            row = sanitize_tool_result(
                {"data": {"columns": [column], "rows": [{column: value}]}},
                report_mode=True, tool_name="get_report_ai_job_data",
            )["data"]["rows"][0]
            expected = REDACTED_PHONE if value == PHONE else REDACTED_NAME
            assert row[column] == expected
            assert sanitize_report_cell(column, value) == expected


def test_streaming_csv_masks_value_level_pii_under_neutral_headers(tmp_path, monkeypatch):
    source = io.StringIO()
    writer = csv.writer(source, delimiter=";")
    writer.writerow(["Значение", "Наименование"])
    writer.writerow([FIO, PHONE])
    writer.writerow(["Иванов ИИ", "Ivanov IV"])
    writer.writerow([f"Рентген {FIO}, тел. {PHONE}", "Шапочка Иванов Пётр Сергеевич"])
    writer.writerow(["Шапочка И. И.", "Рентген В. К."])
    writer.writerow(["Шапочка Иван", "Шапочка Иван Сергеевич"])
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-456-synthetic-test-secret")
    report_export.reset_link_key_cache()
    owner = report_export.owner_segment(domain="synthetic", subject_type="service_bearer", subject_id=457)
    filename = report_export.new_export_filename(report_file_id=457)
    report_export.store_export_stream(
        raw=io.BytesIO(source.getvalue().encode()), delimiter=";", depersonalize=True,
        owner=owner, filename=filename, subject_type="service_bearer", subject_id=457,
        download_name="synthetic-privacy.csv",
    )
    text = (tmp_path / owner / f"{report_export.file_segment(owner, filename)}.csv").read_text(encoding="utf-8-sig")
    assert list(csv.reader(io.StringIO(text), delimiter=";")) == [
        ["Значение", "Наименование"],
        [REDACTED_NAME, REDACTED_PHONE],
        [REDACTED_NAME, REDACTED_NAME],
        [f"Рентген {REDACTED_NAME}, тел. {REDACTED_PHONE}", f"Шапочка {REDACTED_NAME}"],
        [REDACTED_NAME, REDACTED_NAME],
        [REDACTED_NAME, REDACTED_NAME],
    ]


def test_technical_text_does_not_shield_adjacent_name_or_phone():
    cases = (
        (f"Рентген {FIO}, тел. {PHONE}", f"Рентген {REDACTED_NAME}, тел. {REDACTED_PHONE}"),
        ("Шапочка Иванов Пётр Сергеевич", f"Шапочка {REDACTED_NAME}"),
        ("ОБРАБОТКА ОТ Иванов Пётр Сергеевич", f"ОБРАБОТКА ОТ {REDACTED_NAME}"),
        ("Катетер ЦВК Иванов Пётр Сергеевич", f"Катетер ЦВК {REDACTED_NAME}"),
    )
    for source, expected in cases:
        for column in ("Значение", "Наименование"):
            row = sanitize_tool_result(
                {"data": {"columns": [column], "rows": [{column: source}]}},
                report_mode=True, tool_name="get_report_ai_job_data",
            )["data"]["rows"][0]
            assert row[column] == expected
            assert sanitize_report_cell(column, source) == expected


def test_plain_nonreport_text_still_masks_personal_values():
    assert sanitize_tool_result({"description": f"Владелец {FIO}, тел. {PHONE}"}) == {
        "description": f"owner {REDACTED_NAME}, тел. {REDACTED_PHONE}"
    }
    for value in ("Шапочка И. И.", "Рентген В. К.", "Анестезия И. И."):
        assert sanitize_tool_result({"description": value}) == {"description": REDACTED_NAME}


def test_numeric_matrix_preserves_decimal_value_and_phone_boundary():
    values = ("-125.50", "0.25", "9007199254740993", "246800.0000000000")
    payload = {"data": {"columns": ["Сумма", "Телефон"], "rows": [
        {"Сумма": amount, "Телефон": PHONE} for amount in values
    ]}}
    cleaned = sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )
    normalized = normalize_report_rows(cleaned)["data"]["rows"]
    for source, row in zip(values, normalized):
        assert Decimal(str(row["Сумма"])) == Decimal(source)
        assert row["Телефон"] == REDACTED_PHONE
    assert isinstance(normalized[2]["Сумма"], str)


@pytest.mark.asyncio
@respx.mock
async def test_mcp_job_data_matches_synthetic_source_except_declared_redactions():
    billing_mock()
    source = {"success": True, "data": {"columns": list(COLUMNS),
              "rows": _source_rows(), "total": 13, "limited": False}}
    respx.get(f"{BASE}/rest/api/report-ai-job/456/data").mock(
        return_value=httpx.Response(200, json=source)
    )
    headers, runtime = bearer_runtime_patch(
        scopes=(SCOPE_ANALYTICS_READ,), is_depersonalized=True,
    )
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job_data", {"job_id": 456})
    data = result.structured_content["data"]
    expected = _source_rows()
    for index, row in enumerate(expected):
        row["Количество"] = index + 1
        row["Сумма"] = (index + 1) * 100
    for row in expected:
        row["Телефон"] = REDACTED_PHONE
        row["ФИО"] = REDACTED_NAME
    assert data["columns"] == list(COLUMNS)
    assert data["total"] == 13 and data["limited"] is False
    assert data["rows"] == expected


@pytest.mark.asyncio
async def test_local_http_tool_preserves_complete_synthetic_result(capsys):
    source = {"success": True, "data": {"columns": list(COLUMNS),
              "rows": _source_rows(), "total": 13, "limited": False}}
    local_mcp = FastMCP("stage456-synthetic")
    report_ai.register(_ToolRegistrationProxy(local_mcp))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    app = local_mcp.http_app(
        path="/mcp", transport="streamable-http", stateless_http=True,
        json_response=True,
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, ws="none"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    headers, runtime = patch_runtime_credentials(
        "synthetic", "synthetic-key", is_depersonalized=True,
    )
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.01)
        assert server.started
        with headers, runtime, patch.object(report_ai, "_call_vm", AsyncMock(return_value=source)), \
                patch.object(report_ai, "_attach_rating_reminder", AsyncMock(return_value=None)):
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                response = await client.post("/mcp", json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "get_report_ai_job_data", "arguments": {"job_id": 456}},
                }, headers={"Accept": "application/json, text/event-stream",
                            "Authorization": "Bearer synthetic-stage456"})
        assert response.status_code == 200
        body = response.json()["result"]["structuredContent"]
        data = body["data"]
        assert data["columns"] == list(COLUMNS)
        assert data["total"] == 13 and data["limited"] is False
        assert [row["Наименование"] for row in data["rows"]] == list(COMBINATIONS + POSITIONS)
        assert all(row["Телефон"] == REDACTED_PHONE and row["ФИО"] == REDACTED_NAME
                   for row in data["rows"])
        with capsys.disabled():
            print("stage456 local HTTP code=200 body={success: true, columns: 6, rows: 13, total: 13, limited: false, names_exact: 13, pii_masked: true}")
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=5)
        sock.close()

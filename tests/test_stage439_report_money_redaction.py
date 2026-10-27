"""Stage 439: a Report AI money cell must keep its amount and hide phones."""

import pytest

from depersonalization import REDACTED_PHONE, sanitize_report_cell, sanitize_tool_result
from phone_redaction import redact_phone_numbers
from report_row_types import normalize_report_rows


def _clean_row(row, columns=None):
    payload = {"data": {"columns": list(row) if columns is None else columns, "rows": [row]}}
    return sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )["data"]["rows"][0]


def test_money_and_phone_in_the_same_report_row():
    row = _clean_row({
        "Сумма": "246800.0000000000",
        "Выручка": "-246800.5000000000",
        "Телефон": "+7 (999) 123-45-67",
        "Связь": "+7 (999) 123-45-67",
    })
    assert row == {
        "Сумма": "246800.0000000000",
        "Выручка": "-246800.5000000000",
        "Телефон": REDACTED_PHONE,
        "Связь": REDACTED_PHONE,
    }
    normalized = normalize_report_rows({"data": {"columns": list(row), "rows": [row]}})
    assert normalized["data"]["rows"][0]["Сумма"] == 246800
    assert normalized["data"]["rows"][0]["Выручка"] == -246800.5


@pytest.mark.parametrize("amount", [
    "0.0000000000", "873.0000000000", "873,0000000000",
    "246 800.0000000000", "246\u202f800,5000000000",
])
def test_live_formula_column_preserves_money(amount):
    assert _clean_row({"Сумма(Сумма счёта)": amount}) == {"Сумма(Сумма счёта)": amount}


@pytest.mark.parametrize("amount", [
    "246 800.50", "246 800,50", "246 800.50 ₽", "246 800,50 руб",
    "-246 800.50", "-246 800,50 руб",
])
def test_displayed_money_forms_remain_intact(amount):
    assert _clean_row({"Сумма": amount})["Сумма"] == amount


@pytest.mark.parametrize("column,value", [
    ("Сумма", "8.9161234567"),
    ("Сумма", "89991234567"),
    ("Неизвестно", "246800.0000000000"),
    ("Телефон", "246800.0000000000"),
    ("Сумма", "2468000000.50 ₽"),
    ("Сумма", "0.9160000000"),
    ("Сумма", "8.0000000000"),
    ("Сумма", "9161234567,89161234568"),
    ("Сумма", "9161234567.89161234568"),
    ("Сумма", "100.89161234567"),
    ("Сумма телефонов", "873.0000000000"),
])
def test_ambiguous_phone_shapes_are_still_masked(column, value):
    assert REDACTED_PHONE in _clean_row({column: value})[column]


def test_dates_and_clinical_numbers_remain_intact():
    row = _clean_row({"Дата": "2026-10-26", "Клинический ряд": "150 45 60 55 40 мл"})
    assert row == {"Дата": "2026-10-26", "Клинический ряд": "150 45 60 55 40 мл"}


def test_declared_text_money_column_does_not_bypass_phone_mask():
    columns = [{"name": "Сумма", "type": "string"}]
    assert REDACTED_PHONE in _clean_row({"Сумма": "246800.0000000000"}, columns)["Сумма"]


def test_conflicting_money_column_types_do_not_bypass_phone_mask():
    columns = [{"name": "Сумма", "type": "decimal"}, {"name": "Сумма", "type": "string"}]
    with pytest.raises(ValueError, match="collide"):
        _clean_row({"Сумма": "246800.0000000000"}, columns)


def test_other_consumers_keep_shared_phone_matcher():
    amount = "246800.0000000000"
    assert REDACTED_PHONE in sanitize_report_cell("Сумма", amount)
    assert REDACTED_PHONE in sanitize_tool_result({"description": amount})["description"]
    assert "[Filtered]" in __import__("error_tracking")._redact_exception_value(amount)
    assert "[REDACTED]" in (__import__("agent_feedback_service").sanitize_text(amount, limit=500) or "")
    phones = "9161234567,89161234568"
    assert redact_phone_numbers(phones, REDACTED_PHONE) == f"{REDACTED_PHONE},{REDACTED_PHONE}"

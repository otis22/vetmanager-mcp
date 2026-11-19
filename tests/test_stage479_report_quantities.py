"""Report AI quantity cells preserve fixed decimals without exposing contacts."""

import pytest

from depersonalization import REDACTED_PHONE, sanitize_report_cell, sanitize_tool_result
from report_export import build_export_csv


@pytest.mark.parametrize("heading,value", [
    ("Количество услуг", "12.3400000000"),
    ("COUNT услуг", "12.3400000000"),
    ("qty товаров", "12.3400000000"),
    ("Количество услуг", "1\u202f234.5600000000"),
])
def test_quantity_decimal_survives_json_and_csv(heading, value):
    payload = {"data": {"columns": [heading], "rows": [{heading: value}]}}
    actual = sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )["data"]["rows"][0][heading]
    assert actual == value
    assert sanitize_report_cell(heading, value) == value
    csv_text, _, _ = build_export_csv(
        f"{heading}\n{value}\n".encode(), delimiter=",", depersonalize=True
    )
    assert value in csv_text


@pytest.mark.parametrize("value", ["8.0000000000", "8.3400000000"])
def test_quantity_decimal_starting_with_eight_survives_json_and_csv(value):
    heading = "Количество услуг"
    payload = {"data": {"columns": [heading], "rows": [{heading: value}]}}
    actual = sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )["data"]["rows"][0][heading]
    assert actual == value
    assert sanitize_report_cell(heading, value) == value
    csv_text, _, _ = build_export_csv(
        f"{heading}\n{value}\n".encode(), delimiter=",", depersonalize=True
    )
    assert value in csv_text


def test_quantity_heading_still_masks_real_phone_in_json_and_csv():
    heading = "Количество услуг"
    value = "+7 (999) 123-45-67"
    payload = {"data": {"columns": [heading], "rows": [{heading: value}]}}
    actual = sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )["data"]["rows"][0][heading]
    assert actual == REDACTED_PHONE
    assert sanitize_report_cell(heading, value) == REDACTED_PHONE
    csv_text, _, _ = build_export_csv(
        f'{heading}\n"{value}"\n'.encode(), delimiter=",", depersonalize=True
    )
    assert REDACTED_PHONE in csv_text


@pytest.mark.parametrize("value", [
    "-12.3400000000", "+12.3400000000", "7999123456", "79991234567",
])
def test_extended_quantity_does_not_whitelist_signed_or_bare_phone(value):
    heading = "Количество услуг"
    payload = {"data": {"columns": [heading], "rows": [{heading: value}]}}
    actual = sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )["data"]["rows"][0][heading]
    assert REDACTED_PHONE in actual
    assert REDACTED_PHONE in sanitize_report_cell(heading, value)
    csv_text, _, _ = build_export_csv(
        f"{heading}\n{value}\n".encode(), delimiter=",", depersonalize=True
    )
    assert REDACTED_PHONE in csv_text


@pytest.mark.parametrize("heading", [
    "Количество телефонов", "Значение", "count_code", "count identifier",
    "Количество по карте клиента", "qty_contact", "account", "discount",
    "qty owner", "Количество клиента", "Количество владельцев",
])
def test_untrusted_heading_does_not_preserve_phone_shaped_decimal(heading):
    value = "12.3400000000"
    assert REDACTED_PHONE in sanitize_report_cell(heading, value)
    payload = {"data": {"columns": [heading], "rows": [{heading: value}]}}
    actual = sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )["data"]["rows"][0][heading]
    assert REDACTED_PHONE in actual
    csv_text, _, _ = build_export_csv(
        f"{heading}\n{value}\n".encode(), delimiter=",", depersonalize=True
    )
    assert REDACTED_PHONE in csv_text


def test_quantity_exception_stays_with_rows_and_preserves_existing_number_contract():
    heading = "Количество услуг"
    value = "12.3400000000"
    payload = {"data": {"columns": [heading], "rows": [{heading: 12}],
                        "recognized": {"preview_example_row": {heading: value}}}}
    cleaned = sanitize_tool_result(
        payload, report_mode=True, tool_name="get_report_ai_job_data"
    )
    assert cleaned["data"]["rows"][0][heading] == 12
    assert REDACTED_PHONE in cleaned["data"]["recognized"]["preview_example_row"][heading]

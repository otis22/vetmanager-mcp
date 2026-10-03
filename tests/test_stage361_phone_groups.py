"""Explicit contact markers hide ambiguous 3/3/2/2 phones on every path."""

import pytest

from agent_feedback_service import sanitize_text as sanitize_feedback_text
from depersonalization import REDACTED_PHONE, sanitize_tool_result
from error_tracking import _redact_exception_value
from report_export import build_export_csv


@pytest.mark.parametrize("marker", [
    "тел.", "Тел:", "телефон:", "телефона:", "моб.", "мобильный:",
    "звонить", "звоните", "перезвонить", "phone:", "tel:", "контактный телефон:",
    "тел.: #", "phone=", "телефон=",
    "сот.", "сотовый:", "whatsapp:", "вотсап:",
])
@pytest.mark.parametrize("number", ["912 345 67 89", "912.345.67.89"])
def test_marked_number_is_hidden_in_tool_result_and_csv(marker: str, number: str) -> None:
    text = f"{marker} {number}"
    result = sanitize_tool_result({"description": text})
    csv_text, _, _ = build_export_csv(f'Примечание\n"{text}"\n'.encode(), delimiter=",", depersonalize=True)

    assert result["description"] == f"{marker} {REDACTED_PHONE}"
    assert f"{marker} {REDACTED_PHONE}" in csv_text
    assert number not in csv_text


@pytest.mark.parametrize("number", ["912 345 67 89", "912.345.67.89"])
def test_marked_number_is_hidden_in_diagnostics_and_feedback(number: str) -> None:
    text = f"звонить {number}"
    assert _redact_exception_value(text) == "звонить [Filtered]"
    assert sanitize_feedback_text(text, limit=500) == "звонить [REDACTED]"


def test_phone_equals_marker_hides_the_entire_number_in_diagnostics() -> None:
    assert _redact_exception_value("phone=912 345 67 89") == "phone=[Filtered]"


@pytest.mark.parametrize("value", [
    "Диурез: 120 100 80 60 мл", "Показатели 912 345 67 89",
    "телефонная консультация: 120 100 80 60",
    "перезвонить после анализа 112 140 12 10", "тел. 120 100 80 60 мл",
    "тел. 1912 345 67 89", "тел. 912 345 67 891",
])
def test_ambiguous_clinical_rows_survive(value: str) -> None:
    assert sanitize_tool_result({"description": value})["description"] == value
    assert _redact_exception_value(value) == value


def test_contact_marker_does_not_cross_another_number_or_newline() -> None:
    for text in ("тел. 3 мл, показатели 912 345 67 89", "тел.\n912 345 67 89"):
        assert sanitize_tool_result({"description": text})["description"] == text


def test_dotted_clinical_row_survives_tool_and_export() -> None:
    value = "Координаты: 120.100.80.60"
    assert sanitize_tool_result({"description": value})["description"] == value
    csv_text, _, _ = build_export_csv(f"Примечание\n{value}\n".encode(), delimiter=",", depersonalize=True)
    assert value in csv_text


def test_explicit_contact_list_hides_each_number() -> None:
    text = "тел. 912 345 67 89, 913 456 78 90 и 914.222.33.44"
    cleaned = sanitize_tool_result({"description": text})["description"]
    assert cleaned == "тел. [redacted-phone], [redacted-phone] и [redacted-phone]"
    csv_text, _, _ = build_export_csv(f'Примечание\n"{text}"\n'.encode(), delimiter=",", depersonalize=True)
    assert csv_text.count(REDACTED_PHONE) == 3


@pytest.mark.parametrize("text,expected", [
    ("телефон: 79123456789, 913 456 78 90", "телефон: [redacted-phone], [redacted-phone]"),
    ("тел. 912 345 67 89, 8 913 456 78 90, 914 222 33 44",
     "тел. [redacted-phone], [redacted-phone], [redacted-phone]"),
])
def test_contact_list_survives_a_mixed_phone_format(text: str, expected: str) -> None:
    assert sanitize_tool_result({"description": text})["description"] == expected
    csv_text, _, _ = build_export_csv(f'Примечание\n"{text}"\n'.encode(), delimiter=",", depersonalize=True)
    assert csv_text.count(REDACTED_PHONE) == expected.count(REDACTED_PHONE)


@pytest.mark.parametrize("suffix", ["03.10", "9-18", "2 раза"])
def test_a_following_date_hours_or_count_does_not_expose_marked_phone(suffix: str) -> None:
    text = f"тел. 912 345 67 89 {suffix}"
    assert sanitize_tool_result({"description": text})["description"] == f"тел. {REDACTED_PHONE} {suffix}"


def test_longer_clinical_series_is_not_partly_redacted() -> None:
    text = "звонить: 912 345 67 89 10"
    assert sanitize_tool_result({"description": text})["description"] == text


@pytest.mark.parametrize("text", [
    "тел. 120.100.80.60.40.20",
    "звонить: 912 345 67 89 10.",
])
def test_clinical_series_with_dots_is_not_partly_redacted(text: str) -> None:
    assert sanitize_tool_result({"description": text})["description"] == text


def test_structured_phone_fields_mask_even_without_marker() -> None:
    assert sanitize_tool_result({"phone": "912 345 67 89"})["phone"] == REDACTED_PHONE
    csv_text, _, _ = build_export_csv("Телефон\n912 345 67 89\n".encode(), delimiter=",", depersonalize=True)
    assert REDACTED_PHONE in csv_text
    assert "912 345 67 89" not in csv_text

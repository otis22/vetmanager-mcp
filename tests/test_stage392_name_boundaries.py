"""Этап 392: служебные фразы целы, настоящие ФИО скрыты."""

import pytest

from depersonalization import REDACTED_NAME, sanitize_report_value, sanitize_text, sanitize_tool_result


@pytest.mark.parametrize("value", [
    "Без ФИО, телефонов и других персональных данных.",
    "без ФИО",
    "ФИО отсутствует",
    "ООО Ромашка",
    "ИП",
    "Без ИП и ООО",
    "Анализ крови общий",
    "О ФИО говорить не нужно",
    "ФИО Клиника Вера",
    "ФИО ООО Ромашка",
])
def test_service_phrases_remain_whole(value):
    assert sanitize_report_value(value) == value


@pytest.mark.parametrize("value, expected", [
    ("Иван Иванов", REDACTED_NAME),
    ("Иванов И. И.", REDACTED_NAME),
    ("Иванов И.И.", REDACTED_NAME),
    ("Петров-Водкин Пётр Сергеевич", REDACTED_NAME),
    ("Петров-Водкин И. И.", REDACTED_NAME),
    ("Анна-Мария Сергеевна", REDACTED_NAME),
    ("ИВАНОВ ПЁТР СЕРГЕЕВИЧ", REDACTED_NAME),
    ("ООО Иванов Пётр", "ООО " + REDACTED_NAME),
    ("Без ФИО, подписал Иванов И. И.", "Без ФИО, подписал " + REDACTED_NAME),
    ("Без ФИО Иванов Пётр Сергеевич", "Без ФИО " + REDACTED_NAME),
    ("'Иванов И. И.'", "'" + REDACTED_NAME + "'"),
    ("‘Иванов И. И.’", "'" + REDACTED_NAME + "'"),
    ("-Иванов И.И.", "-" + REDACTED_NAME),
    ("'Smith John David'", "'" + REDACTED_NAME + "'"),
    ("O'Connor Anna Sergeevna", REDACTED_NAME),
    ("ФИО John Smith", "ФИО " + REDACTED_NAME),
    ("ФИО Иванов Пётр", "ФИО " + REDACTED_NAME),
])
def test_real_names_still_redacted_as_whole_words(value, expected):
    assert sanitize_report_value(value) == expected


def test_initials_inside_external_quotes_are_scrubbed_in_free_text():
    assert sanitize_text("'Иванов И. И.'") == "'" + REDACTED_NAME + "'"


def test_typographic_inner_dash_does_not_leave_half_surname_in_free_text():
    assert sanitize_text("Петров–Водкин И. И.") == REDACTED_NAME


def test_report_job_echo_preserves_nonpersonal_intent():
    intent = "Количество приёмов по месяцам. Без ФИО, телефонов и других персональных данных."
    result = sanitize_tool_result(
        {"data": {"job": {"intent_text": intent, "status": "ready_to_save"}}},
        report_mode=True,
        tool_name="create_report_ai_job",
    )
    assert result["data"]["job"]["intent_text"] == intent


def test_report_job_echo_still_scrubs_real_name():
    result = sanitize_tool_result(
        {"data": {"job": {"intent_text": "Отчёт для Иванов Пётр"}}},
        report_mode=True,
        tool_name="create_report_ai_job",
    )
    assert result["data"]["job"]["intent_text"] == "Отчёт для " + REDACTED_NAME

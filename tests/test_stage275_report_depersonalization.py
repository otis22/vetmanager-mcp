"""Stage 275 — depersonalization reaches report rows too.

The sanitizer hides personal data by field name, and its dictionary is English.
Report columns are named by generated SQL from a Russian request, so a token
with depersonalization on — the default — got `{"Владелец": "Иванов Пётр
Сергеевич", "Телефон": "+7 918 414-01-11"}` back untouched, while the same row
with `client_name` and `cell_phone` came back redacted.

Three layers now stand between a report and a person's data: the column name,
the value itself, and a requirement written into the report request. None of
them is sufficient alone, which is why there are three.
"""

import pytest

from depersonalization import (
    REDACTED_EMAIL,
    REDACTED_NAME,
    REDACTED_PHONE,
    sanitize_tool_result,
)


def _rows(payload):
    return sanitize_tool_result(payload, report_mode=True)


def test_a_russian_column_name_is_recognised():
    """Layer one. The report speaks the language the request was written in."""
    clean = _rows({"rows": [{"Владелец": "Иванов Пётр Сергеевич", "Телефон": "+7 918 414-01-11"}]})

    row = clean["rows"][0]
    assert row["Владелец"] == REDACTED_NAME
    assert row["Телефон"] == REDACTED_PHONE


@pytest.mark.parametrize(
    "column",
    ["Колонка 1", "col_7", "Кому звонить", "Ответственный", "Контакт"],
)
def test_a_column_nobody_expected_is_cleaned_by_its_values(column):
    """Layer two. A generated report can name a column anything at all."""
    clean = _rows({"rows": [{column: "Иванов Пётр Сергеевич"}, {column: "+7 918 414-01-11"}]})

    assert clean["rows"][0][column] == REDACTED_NAME
    assert clean["rows"][1][column] == REDACTED_PHONE


@pytest.mark.parametrize(
    "written",
    [
        "+7 918 414-01-11",
        "8 (918) 414-01-11",
        "79184140259",
        "8-918-414-01-11",
    ],
)
def test_a_phone_is_found_however_it_is_written(written):
    clean = _rows({"rows": [{"Колонка 1": written}]})

    assert clean["rows"][0]["Колонка 1"] == REDACTED_PHONE


@pytest.mark.parametrize(
    "value",
    [
        "643094100123456",   # микрочип питомца, 15 цифр
        "4600051000057",     # штрихкод товара, 13 цифр
        "7712345678",        # ИНН юрлица, 10 цифр — совпадает по длине с телефоном
        "2026-08-31 10:11",  # дата со временем
        "12345",             # внутренний идентификатор
    ],
)
def test_numbers_that_are_not_phones_survive(value):
    """A report that loses its chip numbers and barcodes is a broken report.

    The one deliberate exception is a ten-digit tax number: it cannot be told
    from a phone by shape alone, and losing it is cheaper than leaking one.
    """
    clean = _rows({"rows": [{"Значение": value}]})

    if value == "7712345678":
        assert clean["rows"][0]["Значение"] == REDACTED_PHONE
    else:
        assert clean["rows"][0]["Значение"] == value


def test_a_full_name_is_found_but_a_clinic_name_is_not():
    clean = _rows({
        "rows": [
            {"Кто": "Петрова Анна Сергеевна"},
            {"Кто": "Иванов И. И."},
            {"Кто": "Клиника Айболит"},
            {"Кто": "ООО Ветмир"},
            {"Кто": "Вакцинация комплексная"},
        ]
    })

    assert clean["rows"][0]["Кто"] == REDACTED_NAME
    assert clean["rows"][1]["Кто"] == REDACTED_NAME
    # Two capitalised words are a name as often as they are a company or a
    # street, and a report that redacts its own service names is useless.
    assert clean["rows"][2]["Кто"] == "Клиника Айболит"
    assert clean["rows"][3]["Кто"] == "ООО Ветмир"
    assert clean["rows"][4]["Кто"] == "Вакцинация комплексная"


def test_an_email_is_found_anywhere():
    clean = _rows({"rows": [{"Что-то": "напишите на owner@example.com сегодня"}]})

    assert REDACTED_EMAIL in clean["rows"][0]["Что-то"]
    assert "owner@example.com" not in clean["rows"][0]["Что-то"]


def test_personal_data_outside_rows_is_cleaned_too():
    """A job carries text in more places than its table: recognised structure,
    candidate titles, the safe error message."""
    clean = _rows({
        "job": {
            "recognized": {"preview_example_row": {"Клиент": "Сидорова Мария Ивановна"}},
            "candidates": [{"title": "Отчёт по Иванов Пётр Сергеевич"}],
            "error_message_safe": "не найден клиент +7 918 414-01-11",
        }
    })

    job = clean["job"]
    assert job["recognized"]["preview_example_row"]["Клиент"] == REDACTED_NAME
    assert "Иванов Пётр Сергеевич" not in job["candidates"][0]["title"]
    assert "+7 918 414-01-11" not in job["error_message_safe"]


def test_an_ordinary_tool_result_is_untouched_by_the_report_layer():
    """Report cleaning is deliberately aggressive; ordinary tools have
    predictable fields and must not lose data to it."""
    payload = {"data": {"good": {"title": "Ампициллин 500", "barcode": "4600051000057"}}}

    assert sanitize_tool_result(payload) == payload


def test_the_report_tools_are_the_ones_that_get_value_cleaning():
    """Wiring, not intent: a mode nothing turns on protects nobody."""
    from tools import REPORT_TOOLS

    assert "get_report_ai_job_data" in REPORT_TOOLS
    assert "get_report_ai_job" in REPORT_TOOLS
    assert "get_report_ai_job_export" in REPORT_TOOLS
    assert "get_clients" not in REPORT_TOOLS


def test_a_depersonalized_token_asks_the_report_not_to_include_personal_data():
    """Layer three, and the only one that works before the data is selected."""
    from types import SimpleNamespace

    from runtime_auth import use_runtime_credentials
    from tools.report_ai import (
        DEPERSONALIZED_INTENT_REQUIREMENT,
        _intent_with_privacy_requirement,
    )

    hidden = SimpleNamespace(is_depersonalized=True, scopes=())
    plain = SimpleNamespace(is_depersonalized=False, scopes=())

    with use_runtime_credentials(hidden):
        asked = _intent_with_privacy_requirement("Отчёт по должникам")
    with use_runtime_credentials(plain):
        untouched = _intent_with_privacy_requirement("Отчёт по должникам")

    assert DEPERSONALIZED_INTENT_REQUIREMENT in asked
    assert untouched == "Отчёт по должникам"


def test_the_requirement_is_constant_so_repeats_stay_repeats():
    """Upstream deduplicates identical requests. A requirement that varied by
    call would make every repeat look new and queue the same report twice."""
    from types import SimpleNamespace

    from runtime_auth import use_runtime_credentials
    from tools.report_ai import _intent_with_privacy_requirement

    hidden = SimpleNamespace(is_depersonalized=True, scopes=())
    with use_runtime_credentials(hidden):
        first = _intent_with_privacy_requirement("Отчёт по должникам")
        second = _intent_with_privacy_requirement("Отчёт по должникам")

    assert first == second


def test_the_reserved_room_is_charged_only_to_the_tokens_that_get_the_requirement():
    """Upstream caps the field; appending after the check would send more than
    it accepts. Charging the room to everyone would quietly shrink the request
    budget of tokens that never receive the requirement."""
    from types import SimpleNamespace

    from exceptions import ToolInputError
    from runtime_auth import use_runtime_credentials
    from tools.report_ai import (
        DEPERSONALIZED_INTENT_REQUIREMENT,
        INTENT_MAX_LENGTH,
        _privacy_requirement_reserve,
        _validate_intent_text,
    )

    reserve = len(DEPERSONALIZED_INTENT_REQUIREMENT) + 2
    with use_runtime_credentials(SimpleNamespace(is_depersonalized=True, scopes=())):
        assert _privacy_requirement_reserve() == reserve
    with use_runtime_credentials(SimpleNamespace(is_depersonalized=False, scopes=())):
        assert _privacy_requirement_reserve() == 0

    longest = "я" * (INTENT_MAX_LENGTH - reserve)
    assert _validate_intent_text(longest, reserve=reserve) == longest
    with pytest.raises(ToolInputError):
        _validate_intent_text("я" * (INTENT_MAX_LENGTH - reserve + 1), reserve=reserve)
    # And the full length still passes for a token that gets no requirement.
    assert _validate_intent_text("я" * INTENT_MAX_LENGTH, reserve=0)


def test_the_report_right_never_comes_without_full_reading():
    """Stage 269 stopped reports being a way around a preset's visibility. That
    only holds while every preset able to start a report can already read what
    a report could reach — nothing else enforces the pairing."""
    from tool_access_registry import TOKEN_PRESET_SCOPES
    from token_scopes import SCOPE_REPORT_AI_WRITE, SUPPORTED_TOKEN_SCOPES

    # Only rights some tool actually asks for: `messaging.read` is a legacy
    # scope no tool requires, so holding it or not changes nothing a report
    # could reach.
    from tool_access_registry import TOOL_REQUIRED_SCOPES

    in_use = {scope for scopes in TOOL_REQUIRED_SCOPES.values() for scope in scopes}
    reading = {
        scope for scope in SUPPORTED_TOKEN_SCOPES if scope.endswith(".read") and scope in in_use
    }
    for preset, scopes in TOKEN_PRESET_SCOPES.items():
        if SCOPE_REPORT_AI_WRITE in scopes:
            assert reading.issubset(set(scopes)), preset


# The probe behind the wording shown to owners: what the three layers stop, and
# what they do not. Written as a test so the claim on the page cannot quietly
# stop being true.
@pytest.mark.parametrize(
    ("value", "expected_to_be_hidden"),
    [
        ("Иванов Пётр Сергеевич", True),
        ("Пётр Сергеевич", True),
        ("Иванов П. С.", True),
        ("+7 918 414-01-11", True),
        ("8 (918) 414-01-11", True),
        ("79184140111", True),
        ("ivanov@example.com", True),
        ("г. Краснодар, ул. Ленина, д. 5, кв. 12", True),
        ("ул. Красная, д. 12", True),
        # Known residual, stated on the page: two words without a patronymic
        # cannot be told from a company or a street by shape.
        ("Иванов Пётр", False),
        ("Иванов", False),
        # And the data a report exists for must survive.
        ("Ампициллин 500 мг", False),
        ("Вакцинация комплексная", False),
        ("Клиника Айболит", False),
        ("Немецкая овчарка", False),
        ("643094100123456", False),
    ],
)
def test_the_probe_behind_the_promise(value, expected_to_be_hidden):
    from depersonalization import sanitize_tool_result

    cleaned = sanitize_tool_result({"rows": [{"c1": value}]}, report_mode=True)["rows"][0]["c1"]

    assert (cleaned != value) is expected_to_be_hidden, cleaned


def test_the_page_states_what_reports_can_and_cannot_promise():
    from web_html import REPORT_PRIVACY_NOTE

    assert "три слоя" in REPORT_PRIVACY_NOTE
    # A promise without its limit is the thing this whole stage came from.
    assert "гарант" in REPORT_PRIVACY_NOTE

"""Stage 277 — the two-word name, closed by a dictionary instead of a shape.

Stage 275 named this leftover out loud and left it in the interface text:
`Иванов Пётр` has exactly the shape of `Клиника Вера` and `Улица Ленина`, so no
rule about shape can separate them. A dictionary can. `Пётр` is a person's
name; `Ленина` is not.

The rule fires on a pair of capitalised words when one of them is a known given
name — never on a lone word, because a pet called `Марта` and a product called
`Роза` are exactly what a report is for.
"""

from __future__ import annotations

import time

import pytest

from depersonalization import (
    REDACTED_NAME,
    REDACTED_PHONE,
    sanitize_report_value,
    sanitize_tool_result,
)
from russian_given_names import GIVEN_NAMES


# ── What must disappear ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "Иванов Пётр",
        "Пётр Иванов",
        "Иванов Петр",
        "ИВАНОВ ПЁТР",
        "иванов пётр".upper(),
        "Ivanov Petr",
        "PETR IVANOV",
        "Смирнова Анна",
        "Анна-Мария Иванова",
        "Петров-Водкин Пётр",
        "Саша Кузнецов",
        "Кузнецова Катя",
    ],
)
def test_a_two_word_name_no_longer_walks_past(value):
    assert sanitize_report_value(value) == REDACTED_NAME


def test_a_name_inside_a_long_comment_is_found():
    """The marker at the start must not switch the protection off for the rest."""
    cleaned = sanitize_report_value("Оплата от Клиника Вера, принимал врач Иванов Пётр")

    assert "Иванов" not in cleaned
    assert "Клиника Вера" in cleaned


# ── The regression stage 275 shipped, found by this stage's own matrix ────────


@pytest.mark.parametrize(
    "value",
    [
        "Стрижка когтей собаке",
        "Анализ крови общий",
        "Вакцинация против бешенства",
        "Приём терапевта первичный",
        "стрижка когтей собаке",
        "Осмотр перед операцией",
    ],
)
def test_three_ordinary_words_are_not_a_name(value):
    """Stage 275 made the three-word rule case-insensitive to catch `IVANOV
    PETR SERGEEVICH`, and the flag also dropped the requirement for capitals.
    Every three words in a row became `[redacted-name]` — in production, for
    every depersonalized token, for a whole day."""
    assert sanitize_report_value(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "Иванов Пётр Сергеевич",
        "ИВАНОВ ПЁТР СЕРГЕЕВИЧ",
        "Ivanov Petr Sergeevich",
        "IVANOV PETR SERGEEVICH",
    ],
)
def test_the_three_word_name_is_still_caught_in_every_script_and_case(value):
    assert sanitize_report_value(value) == REDACTED_NAME


def test_a_name_typed_entirely_in_lower_case_is_taken_by_the_dictionary():
    """What the capitals requirement gives up, the dictionary takes back —
    but only where a known given name stands next to a patronymic."""
    assert sanitize_report_value("петр сергеевич") == REDACTED_NAME
    assert sanitize_report_value("мария ивановна") == REDACTED_NAME


def test_the_lower_case_surname_stays_and_that_is_the_stated_residual():
    """`иванов петр сергеевич` comes back as `иванов [redacted-name]`.

    The surname is not swallowed on purpose: in lower case nothing separates a
    surname from an ordinary word, and a rule that ate the word before the name
    would eat `принимал петр сергеевич` down to nothing. A lone surname is what
    the interface text already calls the residual, so this is that residual and
    not a new one.
    """
    assert sanitize_report_value("иванов петр сергеевич") == f"иванов {REDACTED_NAME}"
    assert sanitize_report_value("принимал петр сергеевич") == f"принимал {REDACTED_NAME}"


@pytest.mark.parametrize(
    "value",
    [
        "Петров-Водкин Пётр Сергеевич",
        "Анна-Мария Иванова Сергеевна",
        "O'Connor Anna Sergeevna",
        "МакДональд Анна Сергеевна",
    ],
)
def test_a_surname_with_a_hyphen_apostrophe_or_inner_capital_goes_whole(value):
    """The first version left `Петров-` behind: half a surname and a broken
    value. One definition of a name word now serves every rule."""
    assert sanitize_report_value(value) == REDACTED_NAME


def test_bare_capitals_are_not_a_name():
    assert sanitize_report_value("А Б В") == "А Б В"


@pytest.mark.parametrize("value", ["вялый паралич", "кулич пасхальный", "калач ржаной"])
def test_the_lower_case_rule_does_not_eat_a_diagnosis(value):
    """`-ич` is a patronymic suffix and also the end of ordinary words; the
    dictionary is what tells them apart."""
    assert sanitize_report_value(value) == value


# ── What must survive ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        # clinics and legal entities
        "Клиника Вера",
        "Ветклиника Надежда",
        "Аптека Роза",
        "Центр Виктория",
        # commercial tails
        "Вера Плюс",
        "Надежда Сервис",
        "Виктория Фарм",
        # places
        "Площадь Гагарина",
        "улица Красных Партизан",
        "улица Вера Волошина",
        "Нижний Новгород",
        "Сквер Победы",
        # holidays and saints
        "Святой Николай",
        "День Победы",
        # breeds, diagnoses, goods, services
        "Мейн Кун",
        "Русская Голубая",
        "Вялый паралич",
        "Королевский Канин",
        # single words that happen to be names
        "Марта",
        "Роза",
        "Роман",
        "Вера",
    ],
)
def test_a_meaningful_value_is_left_alone(value):
    assert sanitize_report_value(value) == value


@pytest.mark.parametrize(
    "value",
    ["2026-08-31 10:11", "643094100123456", "4600000000001"],
)
def test_what_stage_275_already_protected_is_still_protected(value):
    assert sanitize_report_value(value) == value


# ── The decision made on purpose ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    ["Ветклиника Иванов Пётр", "ООО Иванов Пётр", "Vet Petr", "ООО Вера Иванова"],
)
def test_a_marker_beside_a_name_does_not_shield_it(value):
    """A supplier's lost name is a spoiled row; a missed person is a leak."""
    assert REDACTED_NAME in sanitize_report_value(value)


def test_a_surname_on_its_own_is_the_stated_leftover():
    """Not a defect — the residual this stage says out loud it does not close."""
    assert sanitize_report_value("Ivanov") == "Ivanov"
    assert sanitize_report_value("Иванов") == "Иванов"


# ── Wiring and cost ──────────────────────────────────────────────────────────


def test_the_rule_reaches_report_rows_through_the_tool_layer():
    clean = sanitize_tool_result(
        {"rows": [{"Колонка 1": "Иванов Пётр", "Колонка 2": "+7 918 414-01-11"}]},
        report_mode=True,
    )

    assert clean["rows"][0]["Колонка 1"] == REDACTED_NAME
    assert clean["rows"][0]["Колонка 2"] == REDACTED_PHONE


def test_ordinary_tools_are_not_touched_by_the_new_rule():
    clean = sanitize_tool_result({"title": "Иванов Пётр"})

    assert clean["title"] == "Иванов Пётр"


def test_the_dictionary_folds_yo_and_case():
    assert "петр" in GIVEN_NAMES
    assert "Пётр".lower().replace("ё", "е") in GIVEN_NAMES


def test_a_full_size_report_is_still_cleaned_in_well_under_a_second():
    rows = [
        {
            "Владелец": "Иванов Пётр",
            "Клиника": "Клиника Вера",
            "Дата": "2026-08-31 10:11",
            "Чип": "643094100123456",
            "Услуга": "Стрижка когтей",
        }
        for _ in range(10_000)
    ]

    started = time.perf_counter()
    sanitize_tool_result({"rows": rows}, report_mode=True)
    elapsed = time.perf_counter() - started

    assert elapsed < 3.0, f"cleaning 10k rows took {elapsed:.2f}s"

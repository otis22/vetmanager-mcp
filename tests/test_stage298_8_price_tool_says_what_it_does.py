"""Этап 298.8 — описание инструмента цены говорит, что он делает.

Найдено 06.09.2026, когда описание было впервые прочитано **из живого**
`tools/list`, а не из кода: `update_good_sale_price` попадал в generic-ветку
`update_` и уезжал агенту строкой «Update an existing good / service catalog
item». В ней нет ни цены, ни подтверждения, ни того, что группа переоценивается
только процентом, — то есть от «поправить название товара» инструмент неотличим,
хотя весь смысл этапа 298 в двухшаговом подтверждении.

Класс дефекта тот же, что у 298.7: инструмент знает про себя больше, чем
сообщает вызывающему.
"""

from __future__ import annotations

import pytest

from tool_descriptions import compose_tool_description

DESCRIPTION = compose_tool_description("update_good_sale_price") or ""


def test_description_is_not_the_generic_update_line() -> None:
    assert "Update an existing good" not in DESCRIPTION, (
        "generic-строка выдаёт инструмент цены за правку карточки товара"
    )


@pytest.mark.parametrize(
    "must_mention",
    # `clinic_id` — finding третьего прогона ревью: описание говорило «across
    # clinics» без оговорки, хотя код сужает и `good`, и `group`. Модель могла
    # решить, что безопасного сужения нет, хотя параметр есть.
    ["price", "confirm", "preview", "percent", "clinic_id"],
)
def test_description_names_what_the_agent_must_know(must_mention: str) -> None:
    """Четыре факта, без которых вызов будет неверным."""
    assert must_mention in DESCRIPTION.lower()


def test_description_says_the_change_is_visible_to_clients() -> None:
    """Причина подтверждения — не осторожность вообще, а видимость цены."""
    assert "client" in DESCRIPTION.lower()


def test_domain_synonyms_survive() -> None:
    """Синонимы — то, чем инструмент находится по запросу на русском."""
    assert "цена" in DESCRIPTION or "прайс" in DESCRIPTION

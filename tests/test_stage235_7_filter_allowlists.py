"""Этап 235.7 — семь сущностей получили allowlist полей фильтра.

До 04.09.2026 эти инструменты пропускали `filter` насквозь: на прежней пробе у
их эндпоинтов не было записей, и подтвердить имена полей было нечем. Проба
повторена на `devtr6` — записи появились, 68 полей приняты со статусом 200.

Что проверяют тесты: опечатка в имени поля отвергается до похода в Ветменеджер,
а подтверждённое поле проходит. Списки полей взяты из вывода пробы, не из
головы.

Граница знания записана и здесь, и рядом с самим списком: проба подтверждает,
что поле **принимается**, а не что фильтр по нему сужает выборку. Известная
проблема #24 была ровно про принятый и молча проигнорированный фильтр.
"""

from __future__ import annotations

import pytest

from filters import (
    FILTER_FIELDS_BY_ENTITY,
    FilterPropertyValidationError,
    validate_filter_properties,
)


PROBED_ENTITIES = (
    "comboManualName",
    "comboManualItem",
    "goodGroup",
    "partyAccount",
    "partyAccountDoc",
    "storeDocument",
    "suppliers",
)


@pytest.mark.parametrize("entity", PROBED_ENTITIES)
def test_entity_has_a_non_empty_allowlist(entity: str) -> None:
    assert entity in FILTER_FIELDS_BY_ENTITY
    assert FILTER_FIELDS_BY_ENTITY[entity], f"{entity}: пустой allowlist ничего не защищает"


@pytest.mark.parametrize("entity", PROBED_ENTITIES)
def test_id_is_filterable_everywhere(entity: str) -> None:
    """`id` принят пробой у всех семи — если его нет, список собран неверно."""
    assert "id" in FILTER_FIELDS_BY_ENTITY[entity]


@pytest.mark.parametrize("entity", PROBED_ENTITIES)
def test_typo_in_a_field_name_is_rejected_before_the_request(entity: str) -> None:
    """Смысл allowlist: опечатка не уезжает в Ветменеджер молча.

    Отказ локальный и типизированный: `FilterPropertyValidationError`, а не
    общий `ToolError` — по этому типу обёртка инструмента отличает ошибку
    вызывающего от нашей поломки.
    """
    with pytest.raises(FilterPropertyValidationError):
        validate_filter_properties(
            [{"property": "titlee", "operator": "=", "value": 1}],
            FILTER_FIELDS_BY_ENTITY[entity],
        )


@pytest.mark.parametrize("entity", PROBED_ENTITIES)
def test_confirmed_field_passes(entity: str) -> None:
    field = sorted(FILTER_FIELDS_BY_ENTITY[entity])[0]

    validate_filter_properties(
        [{"property": field, "operator": "=", "value": 1}],
        FILTER_FIELDS_BY_ENTITY[entity],
    )


def test_probe_results_are_pinned_not_paraphrased() -> None:
    """Списки прибиты целиком: пересобранный «по смыслу» список — это догадка.

    Значения взяты из вывода `probe_list_filter_contract.py` на `devtr6`
    04.09.2026.
    """
    assert FILTER_FIELDS_BY_ENTITY["comboManualName"] == frozenset(
        {"id", "is_readonly", "name", "title"}
    )
    assert FILTER_FIELDS_BY_ENTITY["goodGroup"] == frozenset(
        {"id", "is_service", "is_show_in_vaccines", "markup", "price_id", "title"}
    )
    assert FILTER_FIELDS_BY_ENTITY["partyAccount"] == frozenset(
        {"add_dt", "edit_dt", "exec_dt", "id", "status", "store_id", "supplier_id"}
    )


def test_special_path_tools_stay_out_of_the_registry() -> None:
    """Четыре инструмента пункта ходят не в обычный list-эндпоинт.

    `get_medical_cards` → `/rest/api/pet`, `get_diagnoses` →
    `/rest/api/MedicalCards/AllDiagnoses`, `get_anonymous_clients` →
    `/rest/api/user/anonymousList`, `get_message_reports` →
    `/rest/api/messages/reports`. Общий контракт `filter`/`sort` там
    неприменим, и запись в реестре создала бы ложное впечатление, что вопрос
    закрыт.
    """
    for absent in ("medicalCards", "diagnoses", "anonymousClients", "messageReports"):
        assert absent not in FILTER_FIELDS_BY_ENTITY

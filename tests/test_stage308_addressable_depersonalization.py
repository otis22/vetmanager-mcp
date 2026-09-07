"""Этап 308: маска скрывает данные, но перестаёт скрывать, о ком речь.

`[redacted-name]` одинаков для всех. Список из десяти должников — десять
неразличимых строк: агент не может ни назвать человека, ни сослаться на него в
следующем ходе, ни дать пользователю открыть карточку. Рядом при этом почти
всегда лежит идентификатор записи, а он по границе приватности от 21.08.2026
персональными данными не является: `[client:123:last_name]` раскрывает модели
ровно столько же, сколько `[redacted-name]`.

Первая половина файла — не про адресность, а про то, что плоский словарь
ключей ошибается в обе стороны. Найдено при разборе 07.09.2026 и проверено
запуском санитайзера: ФИО врача, контактное лицо и почта поставщика уходят
наружу целиком, а название вакцины, название роли и контакты филиала клиники
прячутся зря.
"""

from __future__ import annotations

import re

import pytest

from depersonalization import (
    REDACTED_NAME,
    REDACTED_PHONE,
    sanitize_tool_result,
)

PLACEHOLDER_RE = re.compile(r"^\[[a-z_]+:[1-9]\d*:[A-Za-z0-9_]+\]$")


def _s(payload):
    return sanitize_tool_result(payload)


# --- 308.0: словарь ошибается в обе стороны --------------------------------


def test_a_doctors_full_name_no_longer_leaves_the_building() -> None:
    """`doctor_name` нормализуется в `doctorname`, и такого ключа в словаре нет.

    Те же имена через `get_users` (`last_name`, `first_name`) маскируются —
    обещание режима исполнялось непоследовательно, и это работало на проде.
    """
    out = _s({"inactive_pets": [{"id": 77, "doctor_id": 5, "doctor_name": "Петров Иван"}]})

    assert out["inactive_pets"][0]["doctor_name"] == "[user:5:doctor_name]"


@pytest.mark.parametrize(
    "payload, path",
    [
        ({"vaccinations": [{"id": 3, "name": "Нобивак"}]}, ("vaccinations", 0, "name")),
        ({"role": {"id": 2, "name": "Администратор"}}, ("role", "name")),
        ({"breed": {"id": 9, "name": "Мейн-кун"}}, ("breed", "name")),
    ],
    ids=["вакцина", "роль", "порода"],
)
def test_a_name_that_is_not_a_person_stays_intact(payload, path) -> None:
    """Название вакцины и роли — не персональные данные, а терялись."""
    out = _s(payload)
    for step in path:
        out = out[step]

    assert out != REDACTED_NAME
    assert out in {"Нобивак", "Администратор", "Мейн-кун"}


def test_clinic_contacts_are_not_a_persons_contacts() -> None:
    """Филиал клиники — не человек, и прятать его телефон не за чем.

    Граница приватности от 21.08.2026 говорит про людей. Скрывая контакты
    самой клиники, режим ломал работу без выигрыша в приватности.
    """
    out = _s({"clinics": [{
        "id": 1, "title": "Филиал на Ленина",
        "phone": "+74950000000", "email": "clinic@example.com",
        "address": "Ленина, 1", "internet_address": "https://example.com",
    }]})[  "clinics"][0]

    assert out["phone"] == "+74950000000"
    assert out["email"] == "clinic@example.com"
    assert out["address"] == "Ленина, 1"


def test_a_suppliers_contact_person_and_mail_stop_leaking() -> None:
    """Тот же дефект, что у `doctor_name`, только в другом словаре.

    `contactperson` отсутствует в `_NAME_KEYS`, а `_EMAIL_KEYS` знает только
    `email` и русские варианты — поле `mail` проходило мимо.
    """
    out = _s({"supplier": [{
        "id": 12, "company_name": "ООО Ветснаб",
        "contact_person": "Сидорова Анна", "mail": "anna@vetsnab.ru",
    }]})["supplier"][0]

    assert out["contact_person"] == "[supplier:12:contact_person]"
    assert out["mail"] == "[supplier:12:mail]"
    assert out["company_name"] == "ООО Ветснаб", "название организации — не ПДн"


def test_a_staff_nickname_is_an_identifier_of_a_person_too() -> None:
    """Рядом с замаскированным ФИО открытый ник непоследователен."""
    out = _s({"user": [{"id": 5, "last_name": "Петров", "nickname": "petrov"}]})["user"][0]

    assert out["nickname"] == "[user:5:nickname]"


def test_a_pets_nickname_stays_untouched(  ) -> None:
    """Сторож на снятое правило этапа 290: кличка — не персональные данные.

    Адресной она тоже не становится: адресовать нечего, скрывать нечего.
    """
    out = _s({"data": {"pets": [{"id": 77, "alias": "Барсик", "owner_id": 123}]}})

    assert out["data"]["pets"][0]["alias"] == "Барсик"


# --- 308.1: маска становится адресной ---------------------------------------


def test_two_debtors_are_no_longer_the_same_string() -> None:
    """Главный случай этапа: десять должников были десятью одинаковыми строками."""
    out = _s({"debtors": [
        {"id": 123, "last_name": "Иванова", "cell_phone": "+79990000001"},
        {"id": 456, "last_name": "Петрова", "cell_phone": "+79990000002"},
    ]})["debtors"]

    assert out[0]["last_name"] == "[client:123:last_name]"
    assert out[1]["last_name"] == "[client:456:last_name]"
    assert out[0]["cell_phone"] == "[client:123:cell_phone]"
    assert out[0]["last_name"] != out[1]["last_name"]


def test_a_nested_owner_is_addressed_by_the_parents_identifier() -> None:
    """У владельца под питомцем своего `id` нет — он лежит в родителе.

    Адресовать имя владельца идентификатором питомца значит соврать.
    """
    out = _s({"data": {"pets": [{
        "id": 77, "alias": "Барсик", "owner_id": 123,
        "owner": {"name": "Иванова Мария", "phone": "+79990000001"},
    }]}})["data"]["pets"][0]["owner"]

    assert out["name"] == "[client:123:name]"
    assert out["phone"] == "[client:123:phone]"


def test_a_flat_row_addresses_three_entities_at_once() -> None:
    """Строка `inactive_pets[]` несёт питомца, клиента и сотрудника разом.

    Правило «ближайшая запись» врёт на ней трижды.
    """
    out = _s({"inactive_pets": [{
        "id": 77, "alias": "Барсик",
        "owner_id": 123, "owner_name": "Иванова Мария", "owner_phone": "+79990000001",
        "doctor_id": 5, "doctor_name": "Петров Иван",
    }]})["inactive_pets"][0]

    assert out["owner_name"] == "[client:123:owner_name]"
    assert out["owner_phone"] == "[client:123:owner_phone]"
    assert out["doctor_name"] == "[user:5:doctor_name]"
    assert "77" not in out["owner_name"] + out["doctor_name"]


def test_without_an_identifier_the_mask_stays_irreversible() -> None:
    """Адресовать нечем — значит прежняя маска, а не выдуманный адрес."""
    out = _s({"debtors": [{"last_name": "Иванова", "cell_phone": "+79990000001"}]})["debtors"][0]

    assert out["last_name"] == REDACTED_NAME
    assert out["cell_phone"] == REDACTED_PHONE


def test_free_text_stays_irreversible_even_next_to_an_identifier() -> None:
    """Возражение ревью: у медкарты идентификатор как раз есть.

    Причина необратимости другая — найденное внутри текста ФИО может
    принадлежать владельцу, врачу или третьему лицу, и адрес записи о нём
    ничего не говорит. Адресной становится только подмена целого поля.
    """
    out = _s({"medical_cards": [{
        "id": 42, "patient_id": 77, "doctor_id": 5,
        "description": "Звонил Петров Иван Сергеевич, телефон +79990000001",
    }]})["medical_cards"][0]["description"]

    assert REDACTED_PHONE in out
    assert "medical_card:42" not in out
    assert "+79990000001" not in out


def test_an_aggregator_does_not_confuse_its_sections() -> None:
    """`get_client_profile` смешивает клиента, счета и приёмы в одном ответе."""
    out = _s({
        "client": {"id": 123, "last_name": "Иванова", "cell_phone": "+79990000001"},
        "last_admissions": [{"id": 900, "client_id": 123, "user_id": 5,
                             "doctor_name": "Петров Иван"}],
    })

    assert out["client"]["last_name"] == "[client:123:last_name]"
    assert out["last_admissions"][0]["doctor_name"] == "[user:5:doctor_name]"


# --- формат: плейсхолдер разбирают регексом, значит он обязан быть строгим ---


def test_every_placeholder_has_the_documented_shape() -> None:
    out = _s({"debtors": [{"id": 123, "last_name": "Иванова", "email": "a@b.ru"}]})["debtors"][0]

    for value in (out["last_name"], out["email"]):
        assert PLACEHOLDER_RE.match(value), value


@pytest.mark.parametrize(
    "record",
    [
        {"id": "12; drop", "last_name": "Иванова"},
        {"id": 0, "last_name": "Иванова"},
        {"id": -5, "last_name": "Иванова"},
        {"id": None, "last_name": "Иванова"},
    ],
    ids=["не-число", "ноль", "отрицательный", "пусто"],
)
def test_an_identifier_from_upstream_cannot_break_the_format(record) -> None:
    """`id` приходит от апстрима. Чужое двоеточие сломало бы разбор у клиента."""
    out = _s({"debtors": [record]})["debtors"][0]

    assert out["last_name"] == REDACTED_NAME


def test_an_unexpected_column_name_falls_back_instead_of_inventing_an_address() -> None:
    """Русский ключ колонки в адрес не годится: приложение разбирает латиницей."""
    out = _s({"debtors": [{"id": 123, "имяклиента": "Иванова"}]})["debtors"][0]

    assert out["имяклиента"] == REDACTED_NAME


def test_report_rows_do_not_become_addressable() -> None:
    """Строка отчёта — свободная форма, идентификатора записи там нет."""
    out = sanitize_tool_result(
        {"rows": [{"Владелец": "Иванова Мария"}]}, report_mode=True
    )["rows"][0]

    assert out["Владелец"] == REDACTED_NAME


# --- найдено ревью дифа -----------------------------------------------------


@pytest.mark.parametrize(
    "container",
    ["good", "clinics", "role", "vaccinations"],
    ids=["товар", "клиника", "роль", "вакцина"],
)
def test_free_text_is_still_cleaned_inside_a_non_person_record(container) -> None:
    """Регресс, внесённый вместе с сентинелом `_NOT_A_PERSON`.

    «Эта запись не про человека» верно для её **полей**: название товара и
    телефон филиала — не персональные данные. Но свободный текст внутри такой
    записи набирается руками, и туда попадает что угодно. Ранний возврат
    выключил `sanitize_text` вместе со всем остальным, и телефон с почтой
    поехали наружу сырыми — то есть правка, задуманная против потери данных,
    открыла утечку.
    """
    out = _s({container: [{"id": 1, "description": "Звонил Иван, +79990000001, a@b.ru"}]})
    text = out[container][0]["description"]

    assert "+79990000001" not in text
    assert "a@b.ru" not in text
    assert REDACTED_PHONE in text


def test_a_nested_staff_record_is_addressed_from_the_parent_too() -> None:
    """У вложенного `user` своего `id` может не быть — как у `owner`.

    Без этого один и тот же врач приходит то адресным плейсхолдером, то
    необратимой маской, в зависимости от формы ответа.
    """
    out = _s({"admission": [{"id": 900, "user_id": 5, "user": {"last_name": "Петров"}}]})

    assert out["admission"][0]["user"]["last_name"] == "[user:5:last_name]"


def test_the_placeholder_keeps_the_key_the_application_actually_sees() -> None:
    """Приложение резолвит по имени поля из ответа, а не по нашему внутреннему.

    `camelCase` встречается в ответах наравне со `snake_case`; приведение к
    нижнему регистру дало бы `firstname`, которого в ответе нет.
    """
    out = _s({"client": {"id": 123, "firstName": "Анна", "cell_phone": "+79990000001"}})["client"]

    assert out["firstName"] == "[client:123:firstName]"
    assert out["cell_phone"] == "[client:123:cell_phone]"

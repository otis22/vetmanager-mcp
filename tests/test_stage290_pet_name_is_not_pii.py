"""Этап 290 — кличка и имя без фамилии остаются в тексте обратной связи.

Решение Владимира 03.09.2026. Кличка питомца и одиночное личное имя никого не
опознают: «Рекс» и «Иван» есть у тысяч. Фамилия опознаёт, и она остаётся под
чисткой — вместе с телефоном, почтой и адресом.

Цена прежнего правила была не в приватности, а в пользе: отчёт «поиск не
находит [REDACTED]» невозможно ни воспроизвести, ни понять. Ради защиты,
которая ничего не защищала, терялось содержание жалобы.

Правило действует в двух местах, и одного мало. Санитайзер чистит текст перед
записью — но до него текст готовит модель, которой три разных места велят
подставлять `<patient>`. Поменять только санитайзер значило бы принять решение,
которое ни на что не влияет: кличка исчезнет раньше, чем дойдёт до нас.
"""

from __future__ import annotations

import pytest

import agent_feedback_service as feedback


def _sanitize(text: str):
    return feedback.sanitize_text_with_metadata(text, limit=2000)


@pytest.mark.parametrize(
    "text",
    [
        "pet: Рекс не находится поиском по кличке",
        "кличка Барсик отдаётся без владельца",
        "patient Мурка: приём сохранён, но не виден в списке",
        "PET Bobby is missing from the list",
    ],
)
def test_a_pet_nickname_stays_in_the_text(text: str) -> None:
    result = _sanitize(text)

    assert "[REDACTED]" not in (result.text or ""), f"кличка вычищена: {result.text!r}"
    assert "contextual_patient" not in result.redactions


@pytest.mark.parametrize(
    "text,kept",
    [
        ("Иван просит выгрузку по счетам", "Иван"),
        ("Пётр не видит счёт в списке", "Пётр"),
        ("John cannot open the invoice", "John"),
        ("врач Мария не находится в расписании", "Мария"),
    ],
)
def test_a_first_name_in_free_text_stays(text: str, kept: str) -> None:
    """«Имя без фамилии оставляем» — про свободный текст, и там оно и живёт.

    Санитайзер трогает только размеченные конструкции: `client: X`, `owner: X`,
    телефон, почту, адрес. Имя в обычной фразе он не видел никогда, поэтому
    указание владельца выполняется без единой правки этого правила.
    """
    result = _sanitize(text)

    assert kept in (result.text or ""), f"имя вычищено: {result.text!r}"
    assert "[REDACTED]" not in (result.text or "")


@pytest.mark.parametrize(
    "text",
    [
        "client: Иванов Иван Иванович не видит счёт",
        "owner: John Smith cannot open the invoice",
        "клиент Иванов И.И. просит выгрузку",
        "owner: Иванов",
        "client: Петрова",
        "клиент Сидорский",
        # Найдено внешним ревью: попытка отличать имя от фамилии по списку
        # суффиксов пропускала обычные фамилии, а не экзотику.
        "client: Толстой",
        "owner: Горький",
        "клиент Белая",
        "owner: Кац",
        "client: Smith",
        "owner: Ivanov",
    ],
)
def test_the_client_identity_field_is_still_redacted_whole(text: str) -> None:
    """Значение после метки клиента чистится целиком, включая одно слово.

    Отличать там имя от фамилии по окончанию — соблазнительно и неверно:
    список суффиксов пропускал Толстой, Горький, Белая, Кац, Смит, Ivanov,
    Smith. Метка `client:`/`owner:` означает поле личности клиента, и его
    содержимое чистится всё.
    """
    result = _sanitize(text)

    assert "[REDACTED]" in (result.text or ""), f"фамилия осталась: {result.text!r}"
    assert "contextual_name" in result.redactions


@pytest.mark.parametrize(
    "text,marker",
    [
        ("phone +7 916 123-45-67 не принимается", "phone"),
        ("owner@example.com не получает письма", "email"),
        ("address: Москва, Тверская 1, кв 5", "contextual_address"),
    ],
)
def test_the_rest_of_the_contract_is_untouched(text: str, marker: str) -> None:
    result = _sanitize(text)

    assert "[REDACTED]" in (result.text or "")
    assert marker in result.redactions


def test_a_pet_nickname_alone_no_longer_raises_the_pii_flag() -> None:
    """`possible_pii` — это «санитайзер сработал». Кличка его больше не поднимает."""
    result = _sanitize("pet: Рекс не находится поиском")

    assert not feedback.PRIVACY_REDACTIONS.intersection(result.redactions)


# Поверхности, которые ОБЕЩАЮТ агенту поведение: три исполняемые и две
# документационные. Внешнее ревью показало, что проверка только исполняемых
# зелена при живых старых обещаниях в README и требованиях — а именно по ним
# описания и переписывают в следующий раз.
_PROMISING_SURFACES = (
    "server.py",
    "tool_descriptions.py",
    "tools/feedback.py",
    "README.md",
    "artifacts/technical-requirements-vetmanager-mcp-ru.md",
)


def test_no_surface_still_tells_the_model_to_hide_the_pet_name() -> None:
    """Правило действует, только если его не отменяет ни одно место.

    Роадмап, PRD и AssumptionLog сюда не входят намеренно: они описывают
    историю решения, и `<patient>` там — цитата, а не указание.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]

    for name in _PROMISING_SURFACES:
        text = (root / name).read_text()
        assert "<patient>" not in text, (
            f"{name}: здесь всё ещё велят прятать кличку, решение не подействует"
        )
        assert "<client>" in text, (
            f"{name}: правило про клиента и телефон должно остаться на месте"
        )


def test_the_redaction_version_records_that_the_rule_changed() -> None:
    """Версия санитайзера — то, по чему видно, каким правилом чищен отчёт."""
    assert feedback.REDACTION_VERSION >= 3

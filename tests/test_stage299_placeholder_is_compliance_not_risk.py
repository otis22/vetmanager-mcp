"""Этап 299 — плейсхолдер в отчёте не является признаком персональных данных.

Найдено 05.09.2026 при разборе пункта 246.7. Из 61 отчёта 12 помечены
`possible_pii=true`, и **у всех двенадцати единственная причина** —
`placeholder_seen`: агент написал `<client>`, `<phone>` или `<address>`.

Ровно этого от него требует описание `report_problem`:

    Use placeholders <client>, <owner>, <phone>, and <address>.

То есть флаг «возможны персональные данные» поднимался там, где агент
персональные данные **убрал**, и делал это аккуратнее прочих. Смысл флага
перевёрнут: он должен показывать разбирающему, куда посмотреть глазами, а
показывал самые чистые отчёты. Цена не гипотетическая — `possible_pii` стоит
показателем на дашборде метрик, и «три отчёта с возможными персональными
данными» читалось как утечка.

Сам признак не выбрасывается: он остаётся в наборе `redactions`, просто
перестаёт означать риск. Выбросить его значило бы потерять единственное
свидетельство того, что агент контракт соблюдает.
"""

from __future__ import annotations

import agent_feedback_service as feedback


def test_placeholder_is_not_a_privacy_risk() -> None:
    assert "placeholder_seen" not in feedback.PRIVACY_REDACTIONS


def test_real_leaks_are_still_privacy_risks() -> None:
    """Снятие одного признака не должно ослабить остальные."""
    for marker in ("email", "phone", "contextual_name", "contextual_address"):
        assert marker in feedback.PRIVACY_REDACTIONS


def test_text_with_only_placeholders_is_not_flagged() -> None:
    """Главный случай: отчёт, написанный ровно по инструкции."""
    result = feedback.sanitize_text_with_metadata(
        "Поиск по <client> не находит записи владельца, телефон <phone> не помогает.",
        limit=1000,
    )

    assert "placeholder_seen" in result.redactions, (
        "сам признак должен остаться: он свидетельство соблюдения контракта"
    )
    assert not feedback.PRIVACY_REDACTIONS.intersection(result.redactions)


def test_a_real_phone_is_still_flagged_even_next_to_a_placeholder() -> None:
    """Плейсхолдер рядом не должен обелять настоящий телефон."""
    result = feedback.sanitize_text_with_metadata(
        "Клиент <client> оставил телефон +7 999 200-00-03 в примечании.",
        limit=1000,
    )

    assert "phone" in result.redactions
    assert feedback.PRIVACY_REDACTIONS.intersection(result.redactions)

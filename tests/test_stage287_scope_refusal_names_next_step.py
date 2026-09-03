"""Этап 287.4 — отказ по scope называет следующий шаг.

Отчёт #50: агент честно запросил `pets.write`, получил `invalid_scope` и встал.
Текст отказа сообщал только факт — «этот scope клиенту не разрешён», — и ни
агент, ни человек за ним не могли понять, что делать дальше.

Поток авторизации при этом намеренно не меняется: решение владельца
03.09.2026 — «делай, но без риска сломать OAuth сейчас». Разбор самой проверки
(пункты 287.1–287.3) отложен отдельно.

Проверяется правило, а не фраза целиком: отказ обязан назвать место, где
уровень доступа меняется, и не притворяться, что права выданы.
"""

from __future__ import annotations

from oauth_service import describe_disallowed_scopes


class _Refusal:
    def __init__(self, description: str):
        self.error = "invalid_scope"
        self.description = description


def _refusal_for(scope: str) -> _Refusal:
    return _Refusal(describe_disallowed_scopes(scope.split()))


def test_refusal_points_at_the_cabinet() -> None:
    """Без адреса следующего шага отказ — тупик: агент не знает, что права
    выдаёт владелец в кабинете, а не он сам повторным запросом."""
    error = _refusal_for("pets.write")

    assert error.error == "invalid_scope"
    assert "кабинет" in error.description.lower() or "cabinet" in error.description.lower()


def test_refusal_names_what_was_asked_for() -> None:
    """«Какой-то scope не разрешён» не даёт понять, какой именно из запрошенных
    лишний, когда их несколько."""
    error = _refusal_for("pets.write admissions.write")

    assert "pets.write" in error.description
    assert "admissions.write" in error.description


def test_refusal_does_not_pretend_the_scope_was_granted() -> None:
    error = _refusal_for("pets.write")

    assert "granted" not in error.description.lower()

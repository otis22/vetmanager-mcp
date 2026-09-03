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

import pytest

from oauth_service import describe_disallowed_scopes, get_mcp_resource_url


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


@pytest.mark.asyncio
async def test_the_refusal_text_reaches_the_authorize_response() -> None:
    """Ревью диффа: сторож на хелпер зелен и тогда, когда до пользователя
    доходит другой текст.

    Правило CLAUDE.md §4.0 ровно про это: проверка обязана дёргать тот слой,
    куда доходит выполнение, а не только функцию рядом. Поэтому здесь
    поднимается настоящий `validate_oauth_authorize_request` с настоящим
    клиентом в базе.
    """
    import storage
    from sqlalchemy import delete
    from oauth_service import OAuthRequestError, validate_oauth_authorize_request
    from storage_models import OAuthClient

    async with storage.get_session_factory()() as session:
        # База переживает прогон, а падение на дубликате ключа выглядело бы
        # красным по чужой причине и ничего бы не доказывало.
        await session.execute(
            delete(OAuthClient).where(OAuthClient.client_id == "vm_oc_stage287_guard")
        )
        session.add(
            OAuthClient(
                client_id="vm_oc_stage287_guard",
                client_name="Guard",
                redirect_uris_json='["https://example.org/cb"]',
                token_endpoint_auth_method="none",
                grant_types_json='["authorization_code"]',
                response_types_json='["code"]',
                scope="clients.read offline_access",
                status="active",
            )
        )
        await session.commit()

    params = {
        "client_id": "vm_oc_stage287_guard",
        "redirect_uri": "https://example.org/cb",
        "response_type": "code",
        "scope": "pets.write",
        "code_challenge": "x" * 43,
        "code_challenge_method": "S256",
        "resource": get_mcp_resource_url(),
    }

    async with storage.get_session_factory()() as session:
        with pytest.raises(OAuthRequestError) as excinfo:
            await validate_oauth_authorize_request(session, params)

    error = excinfo.value
    assert error.error == "invalid_scope"
    assert "pets.write" in error.description
    assert "кабинет" in error.description.lower() or "cabinet" in error.description.lower()

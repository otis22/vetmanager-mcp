"""Этапы 287.2 и 287.5 — присланные клиентом права перестают что-либо значить.

Решение владельца 06.09.2026, принятое после разбора 287.1 и **изменившее его
же решение того же дня**. Первое основание — «экран согласия это место, где
клиент может выпросить больше, чем нужно» — не подтвердилось: выпросить больше
на экране нельзя, выдаётся ровно выбранный пресет. А выпросить больше **при
регистрации** можно молча, и на бою 14 клиентов из 27 это уже сделали.

Отсюда: проверка на входе сравнивала запрос клиента с его же собственным
заявлением, то есть не могла остановить того, кому нужны широкие права, и
останавливала ровно того, кто попросил честно и явно. Она снимается.

Главное, что проверяется здесь, — не «отказа больше нет», а что **снятие
проверки ничего не расширило**: выданный доступ как был, так и остался равен
пресету владельца.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

import storage
from oauth_service import (
    OAuthRequestError,
    get_mcp_resource_url,
    narrow_oauth_authorize_request_scope,
    validate_oauth_authorize_request,
)
from storage_models import OAuthClient

CLIENT_ID = "vm_oc_stage287_narrow"
# Клиент заявил при регистрации только чтение клиентов — как те 13 на бою,
# которые ничего лишнего себе не выписали.
DECLARED = "clients.read offline_access"


async def _client_in_db(scope: str = DECLARED) -> None:
    async with storage.get_session_factory()() as session:
        await session.execute(delete(OAuthClient).where(OAuthClient.client_id == CLIENT_ID))
        session.add(
            OAuthClient(
                client_id=CLIENT_ID,
                client_name="Narrow",
                redirect_uris_json='["https://example.org/cb"]',
                token_endpoint_auth_method="none",
                grant_types_json='["authorization_code"]',
                response_types_json='["code"]',
                scope=scope,
                status="active",
            )
        )
        await session.commit()


def _params(scope: str) -> dict:
    return {
        "client_id": CLIENT_ID,
        "redirect_uri": "https://example.org/cb",
        "response_type": "code",
        "scope": scope,
        "code_challenge": "x" * 43,
        "code_challenge_method": "S256",
        "resource": get_mcp_resource_url(),
    }


async def _authorize(scope: str) -> dict:
    await _client_in_db()
    async with storage.get_session_factory()() as session:
        return await validate_oauth_authorize_request(session, _params(scope))


@pytest.mark.asyncio
async def test_scope_beyond_the_registration_reaches_consent() -> None:
    """Ровно тот запрос, который раньше отклонялся у двери (отчёт #50)."""
    request_data = await _authorize("pets.write")

    assert request_data["client_id"] == CLIENT_ID


@pytest.mark.asyncio
async def test_removing_the_check_did_not_widen_anything() -> None:
    """Главная проверка. Клиент просит запись, владелец выбирает отчёты —
    выдаётся отчётный пресет, и записи в нём нет."""
    request_data = await _authorize("pets.write clients.write inventory.write")

    narrowed = narrow_oauth_authorize_request_scope(
        request_data, access_preset="report_ai", confirm_full_access=False
    )

    assert not [scope for scope in narrowed["scopes"] if scope.endswith(".write")
                and scope != "report_ai.write"], (
        f"в выданный доступ просочилась запись: {narrowed['scopes']}"
    )
    assert "pets.write" not in narrowed["scopes"]


@pytest.mark.asyncio
async def test_offline_access_still_survives_to_the_grant() -> None:
    """Это не право на данные клиники, а «не спрашивать владельца заново».
    Потеряй его — подключения начнут отваливаться."""
    request_data = await _authorize("pets.write offline_access")

    narrowed = narrow_oauth_authorize_request_scope(
        request_data, access_preset="report_ai", confirm_full_access=False
    )

    assert "offline_access" in narrowed["oauth_scopes"]


@pytest.mark.asyncio
async def test_unknown_scope_name_is_still_refused() -> None:
    """Разбор запроса — не решение о доступе: несуществующее имя это ошибка
    протокола, и молчать о ней незачем."""
    await _client_in_db()
    async with storage.get_session_factory()() as session:
        with pytest.raises(OAuthRequestError) as excinfo:
            await validate_oauth_authorize_request(session, _params("pets.telepathy"))

    assert excinfo.value.error == "invalid_scope"


def test_the_refusal_text_is_gone_with_the_refusal() -> None:
    """Объяснение того, что больше не происходит, — мусор, который читается
    как действующее правило."""
    import oauth_service

    assert not hasattr(oauth_service, "describe_disallowed_scopes")


# --- 287.5 — экран согласия -------------------------------------------------


def _page() -> str:
    from web_html import render_oauth_consent_page

    return render_oauth_consent_page(
        csrf_token="t",
        request_state="s",
        client_name="ChatGPT",
        connections=[{"id": 1, "domain": "clinic"}],
        selected_access_preset="report_ai",
        script_nonce="n",
    )


def test_consent_page_does_not_list_the_requested_scopes() -> None:
    """Список читался как «вот что будет выдано», хотя выдаётся пресет.
    Показывать рядом с решающей величиной ту, которая ни на что не влияет,
    значит предлагать человеку выбрать не то."""
    page = _page()

    assert "oauth-requested-scopes-technical" not in page
    assert "которые передал" not in page


def test_the_renderer_cannot_be_handed_requested_scopes_at_all() -> None:
    """Убрать раздел мало: пока параметр принимается, список вернётся обратно
    первой же правкой шаблона, и заметит это только человек."""
    import inspect

    from web_html import render_oauth_consent_page

    assert "scopes" not in inspect.signature(render_oauth_consent_page).parameters


def test_consent_page_still_explains_what_each_preset_grants() -> None:
    """Убрать лишнее — не то же самое, что убрать нужное. Права **пресетов**
    остаются: это единственное, что на экране действительно решает."""
    page = _page()

    assert "ChatGPT" in page
    assert "report_ai" in page
    assert "oauth-granted-scopes-technical" in page
    assert "pets.write" in page, "перечень прав пресетов не должен был исчезнуть"


def test_consent_page_says_the_request_does_not_affect_the_grant() -> None:
    """Убрав список, нельзя оставить текст, который его обсуждает: экран
    объяснял, что будет, «если выбрать уровень шире технического запроса», —
    сравнение с величиной, которой на странице больше нет."""
    page = _page()

    assert "на выданные права не влияет" in page
    assert "технического запроса" not in page


# --- Findings внешнего ревью 06.09.2026 --------------------------------------


@pytest.mark.asyncio
async def test_offline_access_survives_when_the_request_omits_scope() -> None:
    """Finding ревью (low). Когда клиент не прислал `scope`, идёт откат на
    заявленное при регистрации — и только там живёт `offline_access` таких
    клиентов. Ветка работала, но сторожа на неё не было, а её поломка тихая:
    подключения начнут просить владельца заново, и никто не свяжет это с
    правкой прав.
    """
    await _client_in_db("clients.read offline_access")
    params = _params("")
    params.pop("scope")

    async with storage.get_session_factory()() as session:
        request_data = await validate_oauth_authorize_request(session, params)

    narrowed = narrow_oauth_authorize_request_scope(
        request_data, access_preset="report_ai", confirm_full_access=False
    )

    assert "offline_access" in narrowed["oauth_scopes"]


@pytest.mark.asyncio
async def test_authorize_request_carries_no_tool_scopes_of_its_own() -> None:
    """Finding ревью (low). После снятия проверки расчёт запрошенных tool
    scopes остался мёртвым, но выглядел как участник решения о доступе.
    Величина, которая ни на что не влияет, но лежит рядом с теми, что влияют, —
    это ложный след для следующего читающего."""
    request_data = await _authorize("pets.write clients.write")

    assert "scopes" not in request_data, (
        "запрошенные tool scopes не должны переживать проверку: их место — "
        "результат выбора владельца, а не запрос клиента"
    )

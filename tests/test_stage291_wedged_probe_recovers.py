"""Этап 291 — брошенная проба не запирает домен навсегда.

Инцидент 04.09.2026, домен `alternativa`: 8 704 отказа подряд за два с
половиной часа, каждый — `circuit breaker half-open; probe already in flight`.
Клиника не могла сделать ни одного запроса, включая `get_cassas`. Вылечилось
только перезапуском процесса.

Механика. После серии таймаутов брейкер открылся, отлежал кулдаун, перешёл в
`half_open` и впустил одну пробу, пометив `probe_in_flight = True`. Флаг
снимается только записью успеха или неудачи этой пробы. В `_request` есть
страховка — `finally` пишет неудачу, если ни одна ветка не отработала, — но
она сама делает `await`, а в отменённой задаче любой новый `await` немедленно
падает с `CancelledError`. Страховка не срабатывает ровно в том случае, ради
которого написана.

Дальше выхода нет: в `half_open` не тикает никакой таймер, кулдаун проверяется
только для `open`. Домен заперт до перезапуска.

Чинится с двух сторон, и обе проверяются здесь:

1. **Срок годности пробы.** Висит дольше срока — считается брошенной,
   впускается новая. Лечит любую причину утечки флага, а не только отмену.
2. **Страховка переживает отмену.** `asyncio.shield` даёт внутренней корутине
   доработать, даже когда наш `await` уже отменён.

Первое — главное: оно не требует, чтобы все пути в коде были безупречны.
"""

from __future__ import annotations

import asyncio

import pytest

from vm_transport.breaker import (
    check_breaker_allows,
    force_breaker_open,
    get_breaker,
    get_breaker_state,
    reset_breakers,
)
from exceptions import VetmanagerUpstreamUnavailable

DOMAIN = "alternativa-test"


@pytest.fixture(autouse=True)
async def _clean_breakers():
    await reset_breakers()
    yield
    await reset_breakers()


async def _wedge_the_probe(*, age_seconds: float) -> None:
    """Воспроизводит инцидент: half_open с пробой, о которой никто не отчитался."""
    await force_breaker_open(DOMAIN, cooldown_elapsed=True)
    await check_breaker_allows(DOMAIN)  # впускает пробу, ставит флаг
    breaker = await get_breaker(DOMAIN)
    async with breaker.lock:
        assert breaker.probe_in_flight is True
        breaker.probe_started_at -= age_seconds


@pytest.mark.asyncio
async def test_a_fresh_probe_still_blocks_everyone_else() -> None:
    """Смысл одиночной пробы сохраняется: пока она жива, остальных не пускаем."""
    await _wedge_the_probe(age_seconds=0.0)

    with pytest.raises(VetmanagerUpstreamUnavailable):
        await check_breaker_allows(DOMAIN)


@pytest.mark.asyncio
async def test_an_abandoned_probe_stops_locking_the_domain(monkeypatch) -> None:
    monkeypatch.setenv("BREAKER_PROBE_TIMEOUT_SECONDS", "60")
    await _wedge_the_probe(age_seconds=61.0)

    # Не должно бросать: проба брошена, впускаем новую.
    await check_breaker_allows(DOMAIN)

    state = get_breaker_state(DOMAIN)
    assert state["state"] == "half_open"
    assert state["probe_in_flight"] is True


@pytest.mark.asyncio
async def test_the_wedge_survives_without_the_deadline(monkeypatch) -> None:
    """Сторож на сам сторож: с огромным сроком годности домен обязан остаться
    запертым — иначе тест выше зелен не из-за срока, а из-за чего-то ещё."""
    monkeypatch.setenv("BREAKER_PROBE_TIMEOUT_SECONDS", "100000")
    await _wedge_the_probe(age_seconds=61.0)

    with pytest.raises(VetmanagerUpstreamUnavailable):
        await check_breaker_allows(DOMAIN)


@pytest.mark.asyncio
async def test_the_probe_does_not_fast_fail_on_its_own_flag(monkeypatch) -> None:
    """Настоящая причина инцидента, найденная после ложной гипотезы.

    Первой версией я обвинил отмену задачи — и написал тест, который оказался
    зелёным и на неисправленном коде: `await` в `finally` на несостязательных
    локах успевает отработать до отмены. Причина другая и точнее ложится на
    жалобу клиники «скрипт в три потока упёрся в лимит API».

    Ответ 429 повторяется, но намеренно **не** считается отказом брейкера:
    ограничение темпа — не признак нездоровья апстрима. Поэтому проба,
    получив 429, идёт на второй заход и перед ним перепроверяет брейкер. Там
    она видит `probe_in_flight = True` — **свой собственный флаг** — считает,
    что пробует кто-то другой, падает с `half-open; probe already in flight`
    и помечает `_breaker_resolved = True`. Аварийный путь после этого
    намеренно ничего не освобождает. Домен заперт навсегда.
    """
    import httpx

    import vetmanager_client as vm_client_module
    from vetmanager_client import VetmanagerClient

    await force_breaker_open(DOMAIN, cooldown_elapsed=True)
    client = _stub_client(monkeypatch, VetmanagerClient)

    class _RateLimited:
        async def request(self, *args, **kwargs):
            return httpx.Response(
                429, headers={"Retry-After": "0"}, request=httpx.Request("GET", "https://x")
            )

    monkeypatch.setattr(
        vm_client_module, "_get_shared_http_client", lambda: _immediate(_RateLimited())
    )
    monkeypatch.setattr(vm_client_module, "_backoff_seconds", lambda *a, **k: 0.0)

    with pytest.raises(Exception):
        await client._request("GET", "/rest/api/cassa")

    state = get_breaker_state(DOMAIN)
    assert state["probe_in_flight"] is False, (
        "проба заперла домен собственным флагом: следующий запрос клиники "
        "получит `probe already in flight` и так до перезапуска процесса"
    )


def _stub_client(monkeypatch, cls):
    from types import SimpleNamespace

    client = cls.__new__(cls)
    client._vetmanager_auth = SimpleNamespace(
        domain=DOMAIN,
        api_key="test-key",
        api_key_fingerprint=lambda: "fp",
        build_headers=lambda: {},
    )
    client._domain = DOMAIN
    client._base_url = "https://example.invalid"
    client._scopes = ()
    client._api_key = "test-key"
    client._auth_source = "test"
    client._account_id = 1
    client._bearer_token_id = None
    client._connection_id = None
    client._last_request_started_at = 0.0
    client._pace_lock = asyncio.Lock()
    client._credentials_lock = asyncio.Lock()
    monkeypatch.setattr(client, "_ensure_runtime_credentials", lambda: asyncio.sleep(0))
    monkeypatch.setattr(client, "_require_scope", lambda *a, **k: None)
    monkeypatch.setattr(client, "_resolve_host", lambda: _immediate("https://example.invalid"))
    monkeypatch.setattr(client, "_headers", lambda: {})
    return client


async def _immediate(value):
    return value

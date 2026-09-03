"""Этап 289.4 — ответы `/mcp` несут идентификатор запроса.

Побочная находка 289.3. Диагноз упавшего смоука обещает `request_id`, по
которому строка находится в журнале прода, — но `attach_request_context_headers`
вызывался только из веб-страниц и выгрузок. На `/mcp` заголовка не было, и в
диагнозе всегда стоял бы прочерк. Проверено на живом контуре: ответ `/` несёт
`x-request-id`, ответ `/mcp` — нет.

Это касается не только смоука: у любого MCP-клиента, поймавшего отказ, не было
ничего, чем связать свой вызов с нашим журналом.

Два теста, и второй важнее первого: middleware, который написан, но не
установлен в приложение, — это ровно тот дефект, ради которого затевался
этап 285.
"""

from __future__ import annotations

import httpx
import pytest

from request_context import CORRELATION_ID_HEADER, REQUEST_ID_HEADER


async def _plain_app(scope, receive, send) -> None:
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_response_carries_a_generated_request_id() -> None:
    from request_context import RequestContextHeaderMiddleware

    app = RequestContextHeaderMiddleware(_plain_app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp")

    assert response.headers.get(REQUEST_ID_HEADER.lower())
    assert response.headers.get(CORRELATION_ID_HEADER.lower())


@pytest.mark.asyncio
async def test_an_inbound_id_is_preserved_not_replaced() -> None:
    """Клиент, который прислал свой идентификатор, должен увидеть его же —
    иначе связать его журнал с нашим по-прежнему нечем."""
    from request_context import RequestContextHeaderMiddleware

    app = RequestContextHeaderMiddleware(_plain_app)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/mcp", headers={REQUEST_ID_HEADER: "client-supplied-id"})

    assert response.headers.get(REQUEST_ID_HEADER.lower()) == "client-supplied-id"


def test_the_middleware_is_actually_installed_on_the_served_app(monkeypatch) -> None:
    """Написанный, но не подключённый middleware — это дефект этапа 285."""
    import server
    from request_context import RequestContextHeaderMiddleware

    captured: dict = {}

    class _Config:
        def __init__(self, app, **kwargs) -> None:
            captured["app"] = app
            captured["kwargs"] = kwargs

    monkeypatch.setattr(server.uvicorn, "Config", _Config)
    class _Server:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def serve(self) -> None:
            return None

    monkeypatch.setattr(server, "_DrainingUvicornServer", _Server)
    monkeypatch.setattr(server.asyncio, "run", lambda coro: None)

    server._run_http_server(
        transport="streamable-http", host="127.0.0.1", port=8000, path="/mcp"
    )

    assert isinstance(captured["app"], RequestContextHeaderMiddleware), (
        "приложение отдаётся uvicorn без middleware — заголовка на /mcp не будет"
    )

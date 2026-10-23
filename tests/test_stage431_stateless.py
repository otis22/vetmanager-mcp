"""Stage 431: MCP POSTs survive an old worker's session disappearing."""

import json

import httpx
import pytest
from fastmcp import FastMCP

import server


HEADERS = {"Accept": "application/json, text/event-stream"}


def _result(response):
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        return json.loads(data)
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["streamable-http", "http"])
async def test_old_worker_session_and_missing_id_work_on_new_worker(monkeypatch, transport):
    test_mcp = FastMCP("stage431")

    @test_mcp.tool()
    def ping() -> str:
        return "pong"

    old_app = test_mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=False, json_response=True)
    initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "stage431", "version": "1"}}}
    async with old_app.router.lifespan_context(old_app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=old_app),
                                     base_url="http://test", headers=HEADERS) as client:
            first = await client.post("/mcp", json=initialize)
            assert first.status_code == 200
            old_id = first.headers["mcp-session-id"]

    monkeypatch.setattr(server, "mcp", test_mcp)
    new_app = server._create_http_app(transport=transport, path="/mcp")
    async with new_app.router.lifespan_context(new_app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=new_app),
                                     base_url="http://test", headers=HEADERS) as client:
            call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "ping", "arguments": {}}}
            stale = await client.post("/mcp", headers={"Mcp-Session-Id": old_id}, json=call)
            assert stale.status_code == 200, stale.text
            assert "pong" in str(_result(stale)["result"])
            fresh = await client.post("/mcp", json=initialize)
            assert fresh.status_code == 200
            assert "mcp-session-id" not in fresh.headers
            notification = await client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            assert notification.status_code == 202
            no_id = await client.post("/mcp", json=call)
            assert no_id.status_code == 200, no_id.text
            assert "pong" in str(_result(no_id)["result"])
            assert (await client.get("/mcp")).status_code == 405


@pytest.mark.parametrize("transport", ["streamable-http", "http"])
def test_served_http_app_uses_the_stateless_default(monkeypatch, transport):
    captured = {}

    class Config:
        def __init__(self, app, **kwargs):
            captured["served_app"] = app

    class Runner:
        def __init__(self, *args, **kwargs):
            captured["runner_kwargs"] = kwargs

        def run(self):
            pass

    monkeypatch.setattr(server.uvicorn, "Config", Config)
    monkeypatch.setattr(server, "_DrainingUvicornServer", Runner)
    original = server._create_http_app
    original_http_app = server.mcp.http_app
    def http_app(**kwargs):
        captured["http_app_kwargs"] = kwargs
        return original_http_app(**kwargs)
    monkeypatch.setattr(server.mcp, "http_app", http_app)
    def create(*, transport, path, stateless_http):
        captured["transport"] = transport
        captured["stateless_http"] = stateless_http
        return original(transport=transport, path=path, stateless_http=stateless_http)
    monkeypatch.setattr(server, "_create_http_app", create)
    server._run_http_server(transport=transport, host="127.0.0.1", port=8000, path="/mcp")
    assert captured["transport"] == transport
    assert captured["stateless_http"] is None
    assert captured["http_app_kwargs"]["stateless_http"] is True
    assert captured["served_app"]
    assert captured["runner_kwargs"]["streamable_http_app"] is not None
    assert captured["runner_kwargs"]["path"] == "/mcp"

@pytest.mark.asyncio
async def test_stateless_requests_do_not_restart_application_lifespan(monkeypatch):
    from contextlib import asynccontextmanager

    entered = 0

    @asynccontextmanager
    async def lifespan(_server):
        nonlocal entered
        entered += 1
        yield

    test_mcp = FastMCP("stage431-lifespan", lifespan=lifespan)

    @test_mcp.tool()
    def ping() -> str:
        return "pong"

    monkeypatch.setattr(server, "mcp", test_mcp)
    app = server._create_http_app(transport="streamable-http", path="/mcp")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test", headers=HEADERS) as client:
            for request_id in range(1, 4):
                response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": request_id,
                                                           "method": "tools/list", "params": {}})
                assert response.status_code == 200
                assert "ping" in str(_result(response)["result"])
                assert entered == 1
    assert entered == 1


def test_stateless_drain_emits_existing_rollout_marker(caplog):
    from types import SimpleNamespace
    import logging
    import shutdown_state

    caplog.set_level(logging.INFO, logger="vetmanager.runtime")
    try:
        shutdown_state.reset_draining()
        shutdown_state.begin_draining()
        manager = SimpleNamespace(_server_instances={})
        assert server._close_sse_for_rollout(manager)
        assert any(record.__dict__.get("event_name") == "streamable_http_drain_finished"
                   and record.__dict__.get("session_count") == 0 for record in caplog.records)
    finally:
        shutdown_state.reset_draining()


def test_deploy_preflight_rejects_stateful_session_header(monkeypatch):
    from scripts import stage385_deploy

    class Response:
        headers = {"mcp-session-id": "worker-session"}
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def read(self, _limit):
            return b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26"}}'

    class Opener:
        def open(self, request, *, timeout):
            assert request.full_url == "http://127.0.0.1:8000/mcp"
            assert request.get_method() == "POST"
            return Response()

    monkeypatch.setattr(stage385_deploy.urllib.request, "build_opener", lambda *_args: Opener())
    with pytest.raises(RuntimeError, match="not stateless MCP"):
        stage385_deploy._stateless_protocol_ready(8000)


def test_deploy_preflight_checks_catalogue_with_stale_and_missing_id(monkeypatch):
    from scripts import stage385_deploy

    methods = []
    headers = []

    class Response:
        headers = {}
        def __init__(self, method):
            self.method = method
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def read(self, _limit):
            result = ({"protocolVersion": "2025-03-26"} if self.method == "initialize"
                      else {"tools": [{"name": "ping"}]})
            return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}).encode()

    class Opener:
        def open(self, request, *, timeout):
            method = json.loads(request.data)["method"]
            methods.append(method)
            headers.append(request.get_header("Mcp-session-id"))
            return Response(method)

    monkeypatch.setattr(stage385_deploy.urllib.request, "build_opener", lambda *_args: Opener())
    stage385_deploy._stateless_protocol_ready(8000)
    assert methods == ["initialize", "initialize", "tools/list", "tools/list"]
    assert headers == [None, "previous-worker-session", None, "previous-worker-session"]


def test_deploy_preflight_rejects_catalogue_error(monkeypatch):
    from scripts import stage385_deploy

    class Response:
        headers = {}
        def __init__(self, method):
            self.method = method
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None
        def read(self, _limit):
            payload = ({"result": {"protocolVersion": "2025-03-26"}}
                       if self.method == "initialize"
                       else {"error": {"code": -32600, "message": "catalogue failed"}})
            return json.dumps({"jsonrpc": "2.0", "id": 1, **payload}).encode()

    class Opener:
        def open(self, request, *, timeout):
            return Response(json.loads(request.data)["method"])

    monkeypatch.setattr(stage385_deploy.urllib.request, "build_opener", lambda *_args: Opener())
    with pytest.raises(RuntimeError, match="not stateless MCP"):
        stage385_deploy._stateless_protocol_ready(8000)

"""Local real-HTTP MCP handshake trace on an isolated test account."""

import asyncio
import json
import logging
import socket

import fakeredis
import httpx
import pytest
import uvicorn
from fastmcp import FastMCP

import mcp_transport_observation as observation
import service_metrics
import storage
from bearer_token_manager import hash_bearer_token
from request_context import RequestContextHeaderMiddleware
from shared_metric_counters import RedisMetricCounters, wait_pending
from storage_models import Account, ServiceBearerToken


def _payload(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: "))
    return response.json()


@pytest.mark.asyncio
async def test_real_http_handshake_is_visible_by_account_and_minute(tmp_path, monkeypatch, caplog):
    # An earlier Alembic test can leave the runtime logger disabled in-process.
    monkeypatch.setattr(observation.RUNTIME_LOGGER.logger, "disabled", False)
    database = tmp_path / "handshake-live.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    storage.reset_storage_state()
    engine = storage.create_database_engine(f"sqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(storage.Base.metadata.create_all)
    token = "vm_st_" + "l" * 43  # synthetic test credential
    async with storage.get_session_factory()() as session:
        account = Account(email="stage453-live@example.invalid")
        session.add(account)
        await session.flush()
        account_id = account.id
        session.add(ServiceBearerToken(account_id=account_id, name="test", token_prefix="stage453live",
            token_hash=hash_bearer_token(token), status="active"))
        await session.commit()

    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
    mcp = FastMCP("stage453-live")
    app = RequestContextHeaderMiddleware(observation.MCPTransportObservationMiddleware(
        mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=True,
                     json_response=True)))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, ws="none"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.01)
        assert server.started
        headers = {"Authorization": "Bearer " + token,
                   "Accept": "application/json, text/event-stream"}
        with caplog.at_level(logging.INFO):
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", headers=headers) as client:
                initialized = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
                    "method": "initialize", "params": {"protocolVersion": "2025-03-26",
                    "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
                listed = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 2,
                    "method": "tools/list", "params": {}})
            await observation.wait_handshake_observations()
            assert await wait_pending()
        assert (initialized.status_code, listed.status_code) == (200, 200)
        assert "protocolVersion" in _payload(initialized)["result"]
        assert isinstance(_payload(listed)["result"]["tools"], list)
        events = [r for r in caplog.records if getattr(r, "event_name", None) == "mcp_handshake"]
        assert len(events) == 2
        assert {r.rpc_method for r in events} == {"initialize", "tools/list"}
        assert {r.account_id for r in events} == {account_id}
        assert {r.observed_at[:16] for r in events} == {events[0].observed_at[:16]}
        assert all(r.http_status == 200 and r.outcome == "success" for r in events)
        assert initialized.headers["x-request-id"] == events[0].request_id
        assert listed.headers["x-request-id"] == events[1].request_id
        assert len(backend.snapshot()["mcp_handshake_total"]) == 2
        print("stage453 local HTTP: initialize=200 body=protocolVersion; tools/list=200 body=tools-array; trace=2 matched events; metric=2")
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, timeout=5)
        finally:
            sock.close()
            await engine.dispose()
            storage.reset_storage_state()

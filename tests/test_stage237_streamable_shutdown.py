import asyncio
import logging
from types import SimpleNamespace

import anyio
import pytest
from fastmcp import FastMCP
from mcp.server.streamable_http import GET_STREAM_KEY, StreamableHTTPServerTransport

from server import (
    STREAMABLE_HTTP_DRAIN_ENABLED_ENV,
    _DrainingUvicornServer,
    _close_standalone_sse_streams,
    _get_streamable_session_manager,
)


class _Transport:
    def __init__(self):
        self.close_calls = 0

    def close_standalone_sse_stream(self):
        self.close_calls += 1


class _SessionManager:
    def __init__(self, *transports):
        self._server_instances = {str(index): transport for index, transport in enumerate(transports)}


def test_drain_closes_only_held_get_streams_and_honors_kill_switch(monkeypatch):
    first = _Transport()
    second = _Transport()
    manager = _SessionManager(first, second)

    assert _close_standalone_sse_streams(manager) == 2
    assert (first.close_calls, second.close_calls) == (1, 1)

    monkeypatch.setenv(STREAMABLE_HTTP_DRAIN_ENABLED_ENV, "false")
    assert _close_standalone_sse_streams(manager) == 0
    assert (first.close_calls, second.close_calls) == (1, 1)


def test_diagnostic_session_manager_lookup_without_lifespan_does_not_log_error(caplog):
    app = SimpleNamespace(routes=[SimpleNamespace(path="/mcp", endpoint=object())])

    caplog.set_level(logging.ERROR, logger="vetmanager.runtime")
    assert _get_streamable_session_manager(app, path="/mcp") is None

    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]

@pytest.mark.asyncio
async def test_uvicorn_shutdown_closes_streams_before_parent(monkeypatch):
    transport = _Transport()
    server = object.__new__(_DrainingUvicornServer)
    server._streamable_session_manager = _SessionManager(transport)
    server._streamable_http_app = None
    server._streamable_http_path = None
    observed = []

    async def parent_shutdown(self, sockets=None):
        observed.append(transport.close_calls)

    monkeypatch.setattr("uvicorn.Server.shutdown", parent_shutdown)
    await _DrainingUvicornServer.shutdown(server)

    assert observed == [1]


@pytest.mark.asyncio
async def test_uvicorn_shutdown_preserves_parent_lifecycle_when_session_manager_lookup_fails(monkeypatch):
    server = object.__new__(_DrainingUvicornServer)
    server._streamable_session_manager = None
    server._streamable_http_app = object()
    server._streamable_http_path = "/mcp"
    observed = []

    def lookup_fails(*_args, **_kwargs):
        raise RuntimeError("SDK wrapper failure")

    async def parent_shutdown(self, sockets=None):
        observed.append(True)

    monkeypatch.setattr("server._get_streamable_session_manager", lookup_fails)
    monkeypatch.setattr("uvicorn.Server.shutdown", parent_shutdown)
    await _DrainingUvicornServer.shutdown(server)

    assert observed == [True]


@pytest.mark.asyncio
async def test_uvicorn_shutdown_logs_error_when_session_manager_is_unavailable(monkeypatch, caplog):
    app = SimpleNamespace(routes=[SimpleNamespace(path="/mcp", endpoint=object())])
    server = object.__new__(_DrainingUvicornServer)
    server._streamable_session_manager = None
    server._streamable_http_app = app
    server._streamable_http_path = "/mcp"

    async def parent_shutdown(self, sockets=None):
        return None

    monkeypatch.setattr("uvicorn.Server.shutdown", parent_shutdown)
    caplog.set_level(logging.ERROR, logger="vetmanager.runtime")
    await _DrainingUvicornServer.shutdown(server)

    assert any(
        record.__dict__.get("event_name") == "streamable_http_drain_unsupported"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_uvicorn_shutdown_kill_switch_skips_session_manager_lookup(monkeypatch):
    server = object.__new__(_DrainingUvicornServer)
    server._streamable_session_manager = None
    server._streamable_http_app = object()
    server._streamable_http_path = "/mcp"
    observed = []

    async def parent_shutdown(self, sockets=None):
        observed.append(True)

    monkeypatch.setenv(STREAMABLE_HTTP_DRAIN_ENABLED_ENV, "false")
    monkeypatch.setattr(
        "server._get_streamable_session_manager",
        lambda *_args, **_kwargs: pytest.fail("lookup must be disabled by the kill switch"),
    )
    monkeypatch.setattr("uvicorn.Server.shutdown", parent_shutdown)
    await _DrainingUvicornServer.shutdown(server)

    assert observed == [True]


@pytest.mark.asyncio
async def test_real_streamable_transport_finishes_all_simultaneous_held_get_streams_without_terminating_sessions():
    mcp = FastMCP("stage237-test")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with app.router.lifespan_context(app):
        manager = _get_streamable_session_manager(app, path="/mcp")
        assert manager is not None
        assert _get_streamable_session_manager(app, path="/mcp") is manager
        held_session_count = 5
        transports = []
        held_get_done = []

        async def read_held_get(receive_stream, done):
            try:
                async with receive_stream:
                    async for _ in receive_stream:
                        pass
            except anyio.ClosedResourceError:
                pass
            done.set()

        held_gets = []
        for index in range(held_session_count):
            session_id = f"held-session-{index}"
            transport = StreamableHTTPServerTransport(mcp_session_id=session_id)
            send_stream, receive_stream = anyio.create_memory_object_stream(0)
            transport._request_streams[GET_STREAM_KEY] = (send_stream, receive_stream)
            manager._server_instances[session_id] = transport
            done = asyncio.Event()
            transports.append(transport)
            held_get_done.append(done)
            held_gets.append(asyncio.create_task(read_held_get(receive_stream, done)))

        await asyncio.sleep(0)
        assert not any(done.is_set() for done in held_get_done)

        assert _close_standalone_sse_streams(manager) == held_session_count
        await asyncio.wait_for(asyncio.gather(*held_gets), timeout=1)
        assert all(done.is_set() for done in held_get_done)
        for index, transport in enumerate(transports):
            assert manager._server_instances[f"held-session-{index}"] is transport
            assert not transport.is_terminated

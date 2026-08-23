import asyncio

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


@pytest.mark.asyncio
async def test_uvicorn_shutdown_closes_streams_before_parent(monkeypatch):
    transport = _Transport()
    server = object.__new__(_DrainingUvicornServer)
    server._streamable_session_manager = _SessionManager(transport)
    observed = []

    async def parent_shutdown(self, sockets=None):
        observed.append(transport.close_calls)

    monkeypatch.setattr("uvicorn.Server.shutdown", parent_shutdown)
    await _DrainingUvicornServer.shutdown(server)

    assert observed == [1]


@pytest.mark.asyncio
async def test_real_streamable_transport_finishes_held_get_stream_without_terminating_session():
    mcp = FastMCP("stage237-test")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    manager = _get_streamable_session_manager(app, path="/mcp")
    assert manager is not None
    assert _get_streamable_session_manager(app, path="/mcp") is manager
    transport = StreamableHTTPServerTransport(mcp_session_id="held-session")
    send_stream, receive_stream = anyio.create_memory_object_stream(0)
    transport._request_streams[GET_STREAM_KEY] = (send_stream, receive_stream)
    manager._server_instances["held-session"] = transport

    normal_response_done = asyncio.Event()
    normal_response_done.set()
    held_get_done = asyncio.Event()

    async def read_held_get():
        try:
            async with receive_stream:
                async for _ in receive_stream:
                    pass
        except anyio.ClosedResourceError:
            pass
        held_get_done.set()

    held_get = asyncio.create_task(read_held_get())
    await asyncio.sleep(0)
    assert normal_response_done.is_set()
    assert not held_get_done.is_set()

    assert _close_standalone_sse_streams(manager) == 1
    await asyncio.wait_for(held_get, timeout=1)
    assert held_get_done.is_set()
    assert manager._server_instances["held-session"] is transport
    assert not transport.is_terminated

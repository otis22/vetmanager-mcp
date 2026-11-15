"""A connected TCP stream must be closed when its caller is cancelled."""

import asyncio
import socket

import anyio
import anyio._core._sockets as sockets
import pytest


@pytest.mark.asyncio
async def test_connected_stream_is_closed_on_outer_cancellation(monkeypatch):
    """Cancel after connect succeeds, while the AnyIO task group is exiting."""
    stream_created = asyncio.Event()

    class FakeStream:
        closed = False

        async def aclose(self):
            self.closed = True

    stream = FakeStream()

    class FakeBackend:
        async def connect_tcp(self, *_args):
            stream_created.set()
            return stream

    async def fake_getaddrinfo(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 1))]

    real_create_group = sockets.create_task_group

    class CancelOnExit:
        def __init__(self):
            self.group = real_create_group()

        async def __aenter__(self):
            await self.group.__aenter__()
            return self

        async def __aexit__(self, *args):
            await stream_created.wait()
            asyncio.current_task().cancel()
            return await self.group.__aexit__(*args)

        @property
        def cancel_scope(self):
            return self.group.cancel_scope

        def start_soon(self, *args):
            return self.group.start_soon(*args)

    monkeypatch.setattr(sockets, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(sockets, "get_async_backend", lambda: FakeBackend())
    monkeypatch.setattr(sockets, "create_task_group", CancelOnExit)

    try:
        with pytest.raises(asyncio.CancelledError):
            await anyio.connect_tcp("fixture.invalid", 1)
    finally:
        task = asyncio.current_task()
        while task.cancelling():
            task.uncancel()

    assert stream.closed, "connected stream survived cancellation before task-group exit"

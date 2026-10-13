"""A draining slot must reject a late write before it reaches MCP/upstream."""

import asyncio

import pytest

from shutdown_state import begin_draining, in_flight_writes, reset_draining


def test_signal_drain_handoff_does_not_enter_held_admission_lock():
    import time
    import shutdown_state

    reset_draining()
    lock = shutdown_state._condition
    with lock:
        started = time.monotonic()
        worker = shutdown_state.request_drain_from_signal()
        assert time.monotonic() - started < 0.1
        assert not shutdown_state._draining
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert shutdown_state.is_draining()
    reset_draining()
from write_admission import WriteAdmissionMiddleware


@pytest.mark.asyncio
async def test_write_after_fence_never_reaches_app():
    reset_draining()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["method"])
        if scope["method"] == "POST":
            entered.set()
            await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    middleware = WriteAdmissionMiddleware(app)

    async def request(method):
        messages = []
        async def send(message):
            messages.append(message)
        await middleware(
            {"type": "http", "method": method, "path": "/mcp"},
            lambda: None,
            send,
        )
        return messages

    try:
        first = asyncio.create_task(request("POST"))
        await entered.wait()
        assert in_flight_writes() == 1
        begin_draining()
        late = await request("POST")
        assert late[0]["status"] == 503
        assert calls == ["POST"]
        assert in_flight_writes() == 1
        release.set()
        assert (await first)[0]["status"] == 200
        assert in_flight_writes() == 0
        assert (await request("GET"))[0]["status"] == 200
    finally:
        release.set()
        reset_draining()

"""Reset closes both async and synchronous clients without losing failures."""

import asyncio

import pytest

import host_resolver
from vm_transport import pool


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["vm", "resolver"])
@pytest.mark.parametrize("kind", ["sync", "async", "missing", "sync_failure"])
async def test_reset_closes_or_retains_client(which, kind):
    loop = asyncio.new_event_loop()
    registry = pool._shared_http_clients if which == "vm" else host_resolver._shared_clients_by_loop
    reset = pool.reset_shared_http_client if which == "vm" else host_resolver.reset_billing_resolver
    locks = host_resolver._shared_clients_locks if which == "resolver" else None

    class Client:
        def __init__(self):
            self.calls = 0
            self.fail = kind == "sync_failure"

        def close(self):
            self.calls += 1
            if self.fail:
                raise RuntimeError("synthetic close failure")

    class AsyncClient(Client):
        async def aclose(self):
            self.calls += 1

    client = object() if kind == "missing" else AsyncClient() if kind == "async" else Client()
    registry[loop] = client
    if locks is not None:
        locks[loop] = asyncio.Lock()
    try:
        if kind in {"missing", "sync_failure"}:
            with pytest.raises(ExceptionGroup, match="cleanup"):
                await reset()
            assert registry[loop] is client
            if locks is not None:
                assert loop in locks
            if kind == "sync_failure":
                client.fail = False
                await reset()
                assert client.calls == 2
        else:
            await reset()
            assert client.calls == 1
        if kind != "missing":
            assert loop not in registry
            if locks is not None:
                assert loop not in locks
    finally:
        registry.pop(loop, None)
        if locks is not None:
            locks.pop(loop, None)
        loop.close()

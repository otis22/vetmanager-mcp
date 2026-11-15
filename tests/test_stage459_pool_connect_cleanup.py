"""Per-pool lifecycle after pre-response transport failures; no real network."""

import asyncio
import os

import anyio
import httpx
import pytest

import host_resolver
from vm_transport import pool


@pytest.mark.asyncio
@pytest.mark.parametrize('which', ['vm', 'resolver'])
@pytest.mark.parametrize('scenario', ['cancel_connect', 'connect_timeout', 'before_send'])
async def test_pool_client_closes_after_interrupted_request(monkeypatch, which, scenario):
    # A real httpx client drives httpcore/AnyIO, but connect_tcp is intercepted.
    started = asyncio.Event()
    calls = []

    async def fake_connect(*_args, **_kwargs):
        calls.append('connect')
        started.set()
        if scenario == 'cancel_connect':
            await asyncio.Event().wait()
        raise TimeoutError('synthetic connect timeout')

    monkeypatch.setattr(anyio, 'connect_tcp', fake_connect)
    getter = pool.get_shared_http_client if which == 'vm' else host_resolver._get_shared_client
    reset = pool.reset_shared_http_client if which == 'vm' else host_resolver.reset_billing_resolver
    registry = pool._shared_http_clients if which == 'vm' else host_resolver._shared_clients_by_loop
    if os.environ.get('STAGE459_MUTATE_POOL_CLOSE') == '1':
        async def reset():
            registry.clear()  # intentional red mutation: drop client without aclose
    client = await getter()
    loop = asyncio.get_running_loop()
    assert registry[loop] is client
    try:
        if scenario == 'before_send':
            raise_before_send = RuntimeError('synthetic pre-send error')
            with pytest.raises(RuntimeError):
                raise raise_before_send
            assert not calls
        elif scenario == 'connect_timeout':
            with pytest.raises(httpx.ConnectTimeout):
                await client.get('http://fixture.invalid/')
            assert calls
        else:
            task = asyncio.create_task(client.get('http://fixture.invalid/'))
            await asyncio.wait_for(started.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls
    finally:
        await reset()
    assert client.is_closed
    assert loop not in registry

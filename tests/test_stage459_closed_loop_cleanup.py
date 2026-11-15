"""Failed pool cleanup keeps clients for an explicit retry."""

import asyncio

import pytest

import host_resolver
from vm_transport import pool


@pytest.mark.asyncio
@pytest.mark.parametrize('which', ['vm', 'resolver'])
async def test_failed_close_retains_client_and_lock_then_retry_succeeds(which):
    failed_loop = asyncio.new_event_loop()
    failed_loop.close()
    good_loop = asyncio.new_event_loop()

    class Client:
        def __init__(self, fail=False):
            self.fail = fail
            self.is_closed = False
            self.attempts = 0

        async def aclose(self):
            self.attempts += 1
            if self.fail:
                raise RuntimeError('owner loop unavailable')
            self.is_closed = True

    failed, good = Client(fail=True), Client()
    registry = pool._shared_http_clients if which == 'vm' else host_resolver._shared_clients_by_loop
    reset = pool.reset_shared_http_client if which == 'vm' else host_resolver.reset_billing_resolver
    registry[failed_loop], registry[good_loop] = failed, good
    lock = None
    if which == 'resolver':
        lock = asyncio.Lock()
        host_resolver._shared_clients_locks[failed_loop] = lock
        host_resolver._shared_clients_locks[good_loop] = asyncio.Lock()
    try:
        with pytest.raises(ExceptionGroup, match='cleanup'):
            await reset()
        assert failed.attempts == good.attempts == 1
        assert registry[failed_loop] is failed
        assert good_loop not in registry and good.is_closed
        if which == 'resolver':
            assert host_resolver._shared_clients_locks[failed_loop] is lock
            assert good_loop not in host_resolver._shared_clients_locks
        failed.fail = False
        await reset()
        assert failed.is_closed and failed.attempts == 2
        assert failed_loop not in registry
        if which == 'resolver':
            assert failed_loop not in host_resolver._shared_clients_locks
    finally:
        registry.pop(failed_loop, None)
        registry.pop(good_loop, None)
        if which == 'resolver':
            host_resolver._shared_clients_locks.pop(failed_loop, None)
            host_resolver._shared_clients_locks.pop(good_loop, None)
        good_loop.close()

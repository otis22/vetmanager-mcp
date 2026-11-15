"""A pending resolver task must not carry open connections into loop shutdown."""

import asyncio

import pytest

import host_resolver


class Connection:
    closed = False

    def close(self):
        self.closed = True


class Client:
    def __init__(self):
        self.connections = [Connection(), Connection()]

    async def aclose(self):
        for connection in self.connections:
            connection.close()


def test_pending_task_cannot_cross_loop_shutdown_with_two_open_connections(monkeypatch):
    owner_loop = asyncio.new_event_loop()
    monkeypatch.setattr(host_resolver, "_LOOKUP_DEADLINE_SECONDS", 0.02)
    resisted = asyncio.Event()
    release = asyncio.Event()

    async def resist_cancellation():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            resisted.set()
            await release.wait()

    task = owner_loop.create_task(resist_cancellation())
    owner_loop.run_until_complete(asyncio.sleep(0))
    client = Client()
    host_resolver._inflight_resolutions_by_loop[owner_loop] = {"one-task-two-connections": task}
    host_resolver._inflight_resolutions_locks[owner_loop] = asyncio.Lock()
    host_resolver._shared_clients_by_loop[owner_loop] = client
    host_resolver._shared_clients_locks[owner_loop] = asyncio.Lock()
    try:
        with pytest.raises(ExceptionGroup, match="cleanup"):
            owner_loop.run_until_complete(host_resolver.reset_billing_resolver())
        assert resisted.is_set()
        assert host_resolver._inflight_resolutions_by_loop[owner_loop]["one-task-two-connections"] is task
        assert host_resolver._shared_clients_by_loop[owner_loop] is client
        assert not any(connection.closed for connection in client.connections)
    finally:
        release.set()
        owner_loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        owner_loop.run_until_complete(host_resolver.reset_billing_resolver())
        owner_loop.close()

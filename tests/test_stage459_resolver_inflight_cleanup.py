"""Shielded resolver tasks must finish before their pooled client closes."""

import asyncio

import pytest
import httpx

import host_resolver


async def _cancel_caller_after_shared_task_starts(monkeypatch, worker_body):
    started = asyncio.Event()
    order = []

    async def fake_uncached(*_args, **_kwargs):
        await host_resolver._get_shared_client()
        started.set()
        try:
            return await worker_body()
        finally:
            order.append('task-done')

    monkeypatch.setattr(host_resolver, '_resolve_vetmanager_host_uncached', fake_uncached)
    caller = asyncio.create_task(host_resolver.resolve_vetmanager_host('fixture', max_retries=0))
    await asyncio.wait_for(started.wait(), 2)
    loop = asyncio.get_running_loop()
    worker = host_resolver._inflight_resolutions_by_loop[loop]['fixture']
    client = host_resolver._shared_clients_by_loop[loop]
    original_close = client.aclose

    async def close():
        order.append('client-close')
        await original_close()

    monkeypatch.setattr(client, 'aclose', close)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert not worker.done(), 'shield must let the owned task outlive caller cancellation'
    return loop, worker, client, order


@pytest.mark.asyncio
async def test_reset_cancels_shielded_task_before_client_close(monkeypatch):
    async def wait_forever():
        await asyncio.Event().wait()

    loop, worker, client, order = await _cancel_caller_after_shared_task_starts(
        monkeypatch, wait_forever)
    try:
        await host_resolver.reset_billing_resolver()
        assert order == ['task-done', 'client-close']
        assert worker.done()
        assert loop not in host_resolver._inflight_resolutions_by_loop
        assert loop not in host_resolver._shared_clients_by_loop
        assert client.is_closed
    finally:
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_resistant_task_retained_then_retry_closes(monkeypatch):
    release = asyncio.Event()
    resisted = asyncio.Event()

    async def resist_once():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            resisted.set()
            await release.wait()
            return 'fixture.invalid'

    loop, worker, client, order = await _cancel_caller_after_shared_task_starts(
        monkeypatch, resist_once)
    monkeypatch.setattr(host_resolver, '_LOOKUP_DEADLINE_SECONDS', 0.02)
    try:
        cleanup_error = None
        try:
            await host_resolver.reset_billing_resolver()
        except ExceptionGroup as exc:
            cleanup_error = exc
        assert host_resolver._inflight_resolutions_by_loop[loop]['fixture'] is worker
        assert cleanup_error is not None
        assert any('inflight' in str(error) for error in cleanup_error.exceptions)
        assert resisted.is_set()
        assert not worker.done() and not client.is_closed
        assert loop in host_resolver._inflight_resolutions_locks
        assert host_resolver._shared_clients_by_loop[loop] is client
        assert 'client-close' not in order
        release.set()
        await worker
        await host_resolver.reset_billing_resolver()
        assert client.is_closed
        assert loop not in host_resolver._inflight_resolutions_by_loop
        assert loop not in host_resolver._shared_clients_by_loop
    finally:
        release.set()
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.asyncio
async def test_completed_callback_keeps_replacement_task_and_reset_is_idempotent():
    loop = asyncio.get_running_loop()
    old = asyncio.create_task(asyncio.sleep(0))
    await old
    replacement = asyncio.create_task(asyncio.Event().wait())
    host_resolver._inflight_resolutions_by_loop[loop] = {'fixture': replacement}
    host_resolver._inflight_resolutions_locks[loop] = asyncio.Lock()
    try:
        host_resolver._clear_inflight_resolution(loop, 'fixture', old)
        assert host_resolver._inflight_resolutions_by_loop[loop]['fixture'] is replacement
    finally:
        replacement.cancel()
        await asyncio.gather(replacement, return_exceptions=True)
    await host_resolver.reset_billing_resolver()
    await host_resolver.reset_billing_resolver()
    assert loop not in host_resolver._inflight_resolutions_by_loop
    assert loop not in host_resolver._inflight_resolutions_locks


@pytest.mark.asyncio
async def test_reset_cancels_all_owned_tasks_before_close():
    loop = asyncio.get_running_loop()
    first = asyncio.create_task(asyncio.Event().wait())
    second = asyncio.create_task(asyncio.Event().wait())
    client = httpx.AsyncClient()
    host_resolver._inflight_resolutions_by_loop[loop] = {'first': first, 'second': second}
    host_resolver._inflight_resolutions_locks[loop] = asyncio.Lock()
    host_resolver._shared_clients_by_loop[loop] = client
    host_resolver._shared_clients_locks[loop] = asyncio.Lock()
    try:
        await host_resolver.reset_billing_resolver()
        assert first.done() and second.done()
        assert client.is_closed
        assert loop not in host_resolver._inflight_resolutions_by_loop
    finally:
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
        if not client.is_closed:
            await client.aclose()


@pytest.mark.asyncio
async def test_reset_drains_completed_task_from_another_loop():
    def make_completed():
        loop = asyncio.new_event_loop()
        task = loop.create_task(asyncio.sleep(0))
        loop.run_until_complete(task)
        return loop, task

    foreign_loop, completed = await asyncio.to_thread(make_completed)
    host_resolver._inflight_resolutions_by_loop[foreign_loop] = {'fixture': completed}
    host_resolver._inflight_resolutions_locks[foreign_loop] = asyncio.Lock()
    try:
        await host_resolver.reset_billing_resolver()
        assert foreign_loop not in host_resolver._inflight_resolutions_by_loop
        assert foreign_loop not in host_resolver._inflight_resolutions_locks
    finally:
        host_resolver._inflight_resolutions_by_loop.pop(foreign_loop, None)
        host_resolver._inflight_resolutions_locks.pop(foreign_loop, None)
        foreign_loop.close()

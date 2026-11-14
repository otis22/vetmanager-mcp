"""Ownership helpers for temporary event loops and live-test child processes."""

import asyncio
import subprocess

import host_resolver
from env_utils import env_float
from vm_transport import pool


async def close_loop_http_clients():
    """Close this loop's clients while their transports can still run callbacks.

    A live HTTP server may own clients on another thread: leave those alone.
    """
    loop = asyncio.get_running_loop()
    clients = [pool._shared_http_clients.pop(loop, None),
               host_resolver._shared_clients_by_loop.pop(loop, None)]
    errors = []
    try:
        for client in clients:
            if client is not None:
                try:
                    await client.aclose()
                except Exception as exc:
                    errors.append(exc)
    finally:
        await asyncio.sleep(env_float("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS", .5,
                                      positive_only=False))
    if errors:
        raise ExceptionGroup("Closing temporary-loop HTTP clients failed", errors)


def stop_processes(processes, timeout=30):
    """Reap every child and close its pipes, preserving captured stderr."""
    for process in processes:
        if process.poll() is None:
            process.terminate()
    logs = []
    for process in processes:
        try:
            _, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate(timeout=5)
        logs.append(stderr or "")
    return logs


def assert_client_absent(result):
    """Accept only the two observed successful absence representations."""
    assert result.get("success") is True
    data = result.get("data", {})
    assert data.get("totalCount") == 0
    assert data.get("client") in ([], {"merge_history": []})


def assert_client_deleted(result, client_id):
    """DELETE may leave the requested record visible with status DELETED."""
    data = result.get("data", {})
    if data.get("totalCount") == 0:
        assert_client_absent(result)
        return
    assert result.get("success") is True and data.get("totalCount") == 1
    record = data.get("client")
    if isinstance(record, list):
        assert len(record) == 1
        record = record[0]
    assert isinstance(record, dict)
    assert str(record.get("id")) == str(client_id)
    assert record.get("status") == "DELETED"

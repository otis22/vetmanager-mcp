"""Temporary browser calls must leave another event loop's clients untouched."""

import asyncio

import httpx

import host_resolver
from vm_transport import pool


def test_run_async_leaves_other_loop_clients_open(run_async):
    other_loop = asyncio.new_event_loop()
    client = httpx.AsyncClient()
    pool._shared_http_clients[other_loop] = client
    host_resolver._shared_clients_by_loop[other_loop] = client
    try:
        run_async(asyncio.sleep(0))
        assert not client.is_closed
        assert pool._shared_http_clients[other_loop] is client
        assert host_resolver._shared_clients_by_loop[other_loop] is client
    finally:
        pool._shared_http_clients.pop(other_loop, None)
        host_resolver._shared_clients_by_loop.pop(other_loop, None)
        other_loop.run_until_complete(client.aclose())
        other_loop.close()

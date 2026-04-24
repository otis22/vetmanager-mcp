"""Shared `httpx.AsyncClient` pool, keyed per running event loop.

Stage 99.4 / 103d: the shared client is keyed on the running event loop.
`asyncio.Lock` is bound to one loop, and `httpx.AsyncClient` also captures
the creating loop for its transport — reusing a singleton across loops
produces "attached to a different event loop" errors in embedded setups
(Jupyter reload, nested `asyncio.run`, cross-test-runner reuse).

Module-level state (`_shared_http_clients`) is intentionally exposed so
`tests/conftest.py` can clear it via dict.clear() between tests — the
dict reference must be stable across `vetmanager_client` re-exports.
"""

from __future__ import annotations

import asyncio
import os
from weakref import WeakKeyDictionary

import httpx

# Split timeouts so a fast-failing DNS/TCP path does not wait the full 30s.
REQUEST_TIMEOUTS = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=2.0)

HTTP_LIMITS = httpx.Limits(
    max_keepalive_connections=50,
    max_connections=100,
    keepalive_expiry=30.0,
)

# Per-loop shared clients, keyed by the loop object itself so closed loops
# auto-evict via weak refs. Mutated in-place, so re-exports from
# `vetmanager_client` MUST bind to this same object rather than copy it.
_shared_http_clients: WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    WeakKeyDictionary()
)

# Lazy lock: avoid import-time asyncio.Lock() bound to whichever loop imports
# the module first. One lock is enough because mutation happens only on
# first-init/reset, not on the hot request path.
_shared_http_client_lock: asyncio.Lock | None = None


def current_loop_key() -> asyncio.AbstractEventLoop | None:
    """Return the currently-running event loop object, else None."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def _get_pool_lock() -> asyncio.Lock:
    global _shared_http_client_lock
    if _shared_http_client_lock is None:
        _shared_http_client_lock = asyncio.Lock()
    return _shared_http_client_lock


async def get_shared_http_client() -> httpx.AsyncClient:
    """Return a shared `httpx.AsyncClient` keyed on the running event loop.

    Lazy-initialized per-loop on first access. Within one loop: same
    keep-alive pool, no fresh TLS handshake per request. Across loops
    (tests that spawn their own loop, notebook reloads): separate clients
    so no cross-loop transport reuse.

    Stage 106.2 (F3 fix): concurrent first-init uses double-check locking
    pattern so N concurrent callers produce ONE AsyncClient (not N, with
    N-1 orphaned and leaking sockets until GC).
    """
    key = current_loop_key()
    if key is None:
        raise RuntimeError("get_shared_http_client() requires a running event loop")
    client = _shared_http_clients.get(key)
    if client is not None and not client.is_closed:
        return client
    # Slow path: acquire lock, re-check, construct if still needed.
    async with _get_pool_lock():
        client = _shared_http_clients.get(key)
        if client is not None and not client.is_closed:
            return client
        if client is not None and client.is_closed:
            _shared_http_clients.pop(key, None)
        new_client = httpx.AsyncClient(timeout=REQUEST_TIMEOUTS, limits=HTTP_LIMITS)
        _shared_http_clients[key] = new_client
        return new_client


async def reset_shared_http_client() -> None:
    """Close and drop ALL per-loop shared clients. For tests and shutdown."""
    clients = list(_shared_http_clients.values())
    _shared_http_clients.clear()
    for c in clients:
        try:
            await c.aclose()
        except Exception:
            pass
    grace_seconds = float(os.environ.get("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS", "0"))
    if grace_seconds > 0:
        # Give asyncio SSL/socket transports time to run close callbacks before
        # pytest's unraisable-warning collector runs under `-W error`.
        await asyncio.sleep(grace_seconds)

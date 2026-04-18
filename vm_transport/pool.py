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

import httpx

# Split timeouts so a fast-failing DNS/TCP path does not wait the full 30s.
REQUEST_TIMEOUTS = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=2.0)

HTTP_LIMITS = httpx.Limits(
    max_keepalive_connections=50,
    max_connections=100,
    keepalive_expiry=30.0,
)

# Per-loop shared clients, keyed by id(running_loop). Mutated in-place
# (dict.clear / dict.pop), so re-exports from `vetmanager_client` MUST
# bind to this same object rather than copy it.
_shared_http_clients: dict[int, httpx.AsyncClient] = {}

# Module-level lock guarding `_shared_http_clients` dict mutations. One
# `asyncio.Lock` is fine because dict mutation is cheap and happens only on
# first-init per loop. Stage 106.2: lock is now actively used by
# `get_shared_http_client` (previously dead code reserved "for BC").
_shared_http_client_lock = asyncio.Lock()


def current_loop_key() -> int:
    """Return a stable key for the currently-running event loop (id of the
    loop object). Falls back to 0 if called outside any loop."""
    try:
        loop = asyncio.get_running_loop()
        return id(loop)
    except RuntimeError:
        return 0


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
    client = _shared_http_clients.get(key)
    if client is not None and not client.is_closed:
        return client
    # Slow path: acquire lock, re-check, construct if still needed.
    async with _shared_http_client_lock:
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

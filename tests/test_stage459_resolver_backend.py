"""Resolver backend cancellation and HTTPX routing ownership guards."""

import asyncio
import os
from types import SimpleNamespace

import httpx
import pytest

import host_resolver
from resolver_network_backend import _ResolverBackend, _ResolverStream, install_resolver_backend


@pytest.mark.asyncio
async def test_tls_cancellation_aborts_transport_without_async_close():
    calls = []
    abort = (lambda: None) if os.environ.get("STAGE459_MUTATE_ABORT") else (
        lambda: calls.append("abort")
    )

    class Inner:
        _stream = SimpleNamespace(_transport=SimpleNamespace(abort=abort))

        async def start_tls(self, *_args, **_kwargs):
            raise asyncio.CancelledError

        async def aclose(self):
            calls.append("aclose")

    with pytest.raises(asyncio.CancelledError):
        await _ResolverStream(Inner()).start_tls(None)
    assert calls == ["abort"]


@pytest.mark.asyncio
async def test_abort_failure_is_explicit():
    def fail():
        raise RuntimeError("abort failed")

    class Inner:
        _stream = SimpleNamespace(_transport=SimpleNamespace(abort=fail))

        async def start_tls(self, *_args, **_kwargs):
            raise asyncio.CancelledError

    with pytest.raises(RuntimeError, match="abort failed"):
        await _ResolverStream(Inner()).start_tls(None)


@pytest.mark.asyncio
async def test_normal_tls_exception_does_not_double_close():
    calls = []

    class Inner:
        _stream = SimpleNamespace(_transport=SimpleNamespace(abort=lambda: calls.append("abort")))

        async def start_tls(self, *_args, **_kwargs):
            raise ValueError("ordinary failure")

    with pytest.raises(ValueError):
        await _ResolverStream(Inner()).start_tls(None)
    assert calls == []


@pytest.mark.asyncio
async def test_backend_preserves_direct_and_proxy_pool_identity(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://fixture.invalid")
    monkeypatch.setenv("NO_PROXY", "")
    client = httpx.AsyncClient()
    try:
        mounts_before = dict(client._mounts)
        transports = [client._transport, *(t for t in mounts_before.values() if t is not None)]
        pools = [transport._pool for transport in transports]
        pool_types = [type(pool) for pool in pools]
        ssl_contexts = [getattr(pool, "_ssl_context", None) for pool in pools]
        assert len(pools) >= 2
        install_resolver_backend(client)
        assert client._mounts == mounts_before
        assert [transport._pool for transport in transports] == pools
        assert [type(pool) for pool in pools] == pool_types
        assert [getattr(pool, "_ssl_context", None) for pool in pools] == ssl_contexts
        assert all(isinstance(pool._network_backend, _ResolverBackend) for pool in pools)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_closed_resolver_client_is_replaced():
    first = await host_resolver._get_shared_client()
    await first.aclose()
    second = await host_resolver._get_shared_client()
    assert second is not first and not second.is_closed
    await host_resolver.reset_billing_resolver()
    assert second.is_closed

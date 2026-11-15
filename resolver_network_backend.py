"""Resolver-only cancellation cleanup for HTTPcore's AnyIO TLS transport."""

import asyncio

import httpcore
from httpcore._backends.anyio import AnyIOBackend


class _ResolverStream(httpcore.AsyncNetworkStream):
    def __init__(self, inner: httpcore.AsyncNetworkStream):
        self._inner = inner

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._inner.read(max_bytes, timeout=timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._inner.write(buffer, timeout=timeout)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        try:
            stream = await self._inner.start_tls(
                ssl_context, server_hostname=server_hostname, timeout=timeout
            )
        except asyncio.CancelledError:
            source = self._inner._stream  # httpcore AnyIOStream private field
            while hasattr(source, "transport_stream"):
                source = source.transport_stream
            transport = source._transport  # AnyIO SocketStream private field
            transport.abort()
            raise
        return _ResolverStream(stream)

    def get_extra_info(self, info: str):
        return self._inner.get_extra_info(info)


class _ResolverBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self._inner = AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        stream = await self._inner.connect_tcp(
            host, port, timeout=timeout, local_address=local_address,
            socket_options=socket_options,
        )
        return _ResolverStream(stream)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        stream = await self._inner.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options,
        )
        return _ResolverStream(stream)

    async def sleep(self, seconds):
        await self._inner.sleep(seconds)


def install_resolver_backend(client) -> None:
    """Attach before first send; retain HTTPX's transport, pool and proxy mounts."""
    transports = [client._transport, *client._mounts.values()]
    pools = []
    for transport in transports:
        if transport is None:
            continue
        pool = getattr(transport, "_pool", None)
        if pool is None or not hasattr(pool, "_network_backend"):
            raise RuntimeError("Unsupported resolver HTTP transport shape")
        pools.append(pool)
    for pool in pools:
        pool._network_backend = _ResolverBackend()

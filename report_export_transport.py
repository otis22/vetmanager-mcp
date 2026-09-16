"""HTTP transport that connects report exports only to pre-validated IPs."""

from __future__ import annotations

import time
from typing import AsyncIterable

import httpcore
import httpx

from report_export_origin import (
    ExportTarget,
    parse_allowed_origins as parse_allowed_origins,
    resolve_export_target as resolve_export_target,
)


_EXCEPTION_MAP = (
    (httpcore.ConnectTimeout, httpx.ConnectTimeout),
    (httpcore.ReadTimeout, httpx.ReadTimeout),
    (httpcore.WriteTimeout, httpx.WriteTimeout),
    (httpcore.PoolTimeout, httpx.PoolTimeout),
    (httpcore.ConnectError, httpx.ConnectError),
    (httpcore.ReadError, httpx.ReadError),
    (httpcore.WriteError, httpx.WriteError),
    (httpcore.RemoteProtocolError, httpx.RemoteProtocolError),
    (httpcore.LocalProtocolError, httpx.LocalProtocolError),
    (httpcore.ProxyError, httpx.ProxyError),
    (httpcore.UnsupportedProtocol, httpx.UnsupportedProtocol),
)


class _PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, target: ExportTarget, backend: httpcore.AsyncNetworkBackend):
        self._target = target
        self._backend = backend
        self.connect_called = False

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host.rstrip(".").lower() != self._target.hostname or port != 443:
            raise httpcore.ConnectError("Export transport target changed.")
        self.connect_called = True
        deadline = time.monotonic() + (timeout if timeout is not None else 10.0)
        last_error: Exception | None = None
        for index, address in enumerate(self._target.addresses):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise httpcore.ConnectTimeout("Export storage connect timed out.")
            attempt_timeout = remaining / (len(self._target.addresses) - index)
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=attempt_timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("Export storage has no validated address.")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are disabled for report exports.")

    async def sleep(self, seconds):
        await self._backend.sleep(seconds)


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterable[bytes]):
        self._stream = stream

    async def __aiter__(self):
        async for part in self._stream:
            yield part

    async def aclose(self) -> None:
        await self._stream.aclose()  # type: ignore[attr-defined]


class PinnedExportTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        target: ExportTarget,
        *,
        network_backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._target = target
        self._backend = _PinnedNetworkBackend(
            target, network_backend or httpcore.AnyIOBackend()
        )
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=1,
            max_keepalive_connections=0,
            network_backend=self._backend,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            response = await self._pool.handle_async_request(core_request)
        except httpcore.NetworkError as exc:
            raise _mapped_exception(exc, request) from None
        except httpcore.TimeoutException as exc:
            raise _mapped_exception(exc, request) from None
        except httpcore.ProtocolError as exc:
            raise _mapped_exception(exc, request) from None
        if not self._backend.connect_called:
            await response.aclose()
            raise httpx.ConnectError("Pinned export transport was not used.", request=request)
        return httpx.Response(
            status_code=response.status,
            headers=response.headers,
            stream=_ResponseStream(response.stream),
            extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


def _mapped_exception(exc: Exception, request: httpx.Request) -> httpx.HTTPError:
    for source, destination in _EXCEPTION_MAP:
        if isinstance(exc, source):
            return destination("Export storage transport failed.", request=request)
    return httpx.TransportError("Export storage transport failed.", request=request)

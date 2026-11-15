"""Offline TLS resolver lifecycle with real httpx/AnyIO sockets."""

import asyncio
import gc
from importlib.metadata import version
import os
from pathlib import Path
import ssl
import subprocess

from _pytest.unraisableexception import collect_unraisable
import pytest

import host_resolver
from tests.transport_diagnostics import snapshot_fds, write_diagnostic


def _socket_identities():
    return {tuple(row["identity"]) for row in snapshot_fds().values()
            if row["kind"] == "socket"}


def _test_cert(tmp_path):
    cert = tmp_path / "local-cert.pem"
    key = tmp_path / "local-key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
         "-keyout", str(key), "-out", str(cert), "-days", "1",
         "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return cert, context


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["handshake_timeout", "headers_timeout", "success"])
async def test_resolver_tls_cancel_and_reset(monkeypatch, request, tmp_path, scenario):
    candidate_cleanup = os.environ.get("STAGE459_TLS_CANDIDATE_CLEANUP") == "1"
    if candidate_cleanup:
        from httpcore._backends.anyio import AnyIOStream

        original_start_tls = AnyIOStream.start_tls

        async def close_on_cancellation(self, *args, **kwargs):
            try:
                return await original_start_tls(self, *args, **kwargs)
            except asyncio.CancelledError:
                await self.aclose()
                raise

        monkeypatch.setattr(AnyIOStream, "start_tls", close_on_cancellation)
    cert, tls_context = _test_cert(tmp_path)
    phases = []
    writers = []
    server_socket_ids = set()
    second_started = asyncio.Event()
    accepted = 0

    async def serve(reader, writer):
        nonlocal accepted
        accepted += 1
        writers.append(writer)
        info = os.fstat(writer.get_extra_info("socket").fileno())
        server_socket_ids.add((info.st_dev, info.st_ino))
        try:
            if scenario == "handshake_timeout":
                if accepted == 2:
                    second_started.set()
                while await reader.read(4096):
                    pass
            else:
                await reader.readuntil(b"\r\n\r\n")
                if scenario == "success":
                    body = b'{"url":"https://fixture.vetmanager.ru"}'
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                        + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body
                    )
                    await writer.drain()
                else:
                    if accepted == 2:
                        second_started.set()
                    await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    before = _socket_identities()
    server = await asyncio.start_server(
        serve, "127.0.0.1", 0,
        ssl=None if scenario == "handshake_timeout" else tls_context,
    )
    port = server.sockets[0].getsockname()[1]
    listener_info = os.fstat(server.sockets[0].fileno())
    server_socket_ids.add((listener_info.st_dev, listener_info.st_ino))
    template = f"https://127.0.0.1:{port}/{{domain}}"
    monkeypatch.setattr(host_resolver, "BILLING_API", template)
    monkeypatch.setattr(host_resolver, "BILLING_API_ALIAS", template)
    monkeypatch.setattr(host_resolver, "_BILLING_LOOKUP_DEADLINE_SECONDS", 0.2)
    monkeypatch.setenv("SSL_CERT_FILE", str(cert))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    loop = asyncio.get_running_loop()
    caller = asyncio.create_task(host_resolver.resolve_vetmanager_host("fixture", max_retries=0))
    client = None
    opened = set()
    try:
        if scenario == "success":
            assert await asyncio.wait_for(caller, 3) == "https://fixture.vetmanager.ru"
            phases.append("successful_resolve")
        else:
            await asyncio.wait_for(second_started.wait(), 3)
            assert accepted == 2
            phases.append("first_bounded_timeout_second_connect")
            worker = host_resolver._inflight_resolutions_by_loop[loop]["fixture"]
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert not worker.done()
            phases.append("shielded_worker_pending_after_caller_cancel")
        client = host_resolver._shared_clients_by_loop[loop]
        opened = _socket_identities() - before
        assert opened
        await host_resolver.reset_billing_resolver()
        phases.append("reset_completed")
        assert client.is_closed
        assert loop not in host_resolver._shared_clients_by_loop
        assert loop not in host_resolver._inflight_resolutions_by_loop
    finally:
        if not caller.done():
            caller.cancel()
            await asyncio.gather(caller, return_exceptions=True)
        await host_resolver.reset_billing_resolver()
        for writer in writers:
            writer.close()
            await writer.wait_closed()
        server.close()
        await server.wait_closed()
    remaining_before_gc = opened & _socket_identities()
    gc.collect()
    warning_error = None
    try:
        collect_unraisable(request.config)
    except BaseException as exc:
        warning_error = exc
    remaining = opened & _socket_identities()
    if warning_error is None:
        phases.append("gc_unraisable_clean")
    evidence_dir = os.environ.get("STAGE459_TLS_EVIDENCE_DIR")
    if evidence_dir:
        write_diagnostic(
            Path(evidence_dir) / f"tls-{scenario}.json",
            {"scenario": scenario, "candidate_cleanup": candidate_cleanup,
             "versions": {name: version(name) for name in
             ("anyio", "httpx", "httpcore", "uvloop")}, "phases": phases,
             "connections_accepted": accepted, "opened_socket_count": len(opened),
             "remaining_before_gc_count": len(remaining_before_gc),
             "remaining_before_gc_server_count": len(remaining_before_gc & server_socket_ids),
             "remaining_before_gc_nonserver_count": len(remaining_before_gc - server_socket_ids),
             "remaining_socket_count": len(remaining),
             "remaining_server_socket_count": len(remaining & server_socket_ids),
             "remaining_nonserver_socket_count": len(remaining - server_socket_ids),
             "reset_exception_group": False,
             "warning_error_class": type(warning_error).__name__ if warning_error else None,
             "client_closed": client.is_closed},
        )
    if warning_error is not None:
        raise warning_error
    assert not remaining

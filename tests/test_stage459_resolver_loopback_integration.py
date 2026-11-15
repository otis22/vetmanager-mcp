"""Offline resolver transport lifecycle through real loopback TCP sockets."""

import asyncio
import gc
from importlib.metadata import version
import os
from pathlib import Path

from _pytest.unraisableexception import collect_unraisable
import pytest

import host_resolver
from tests.transport_diagnostics import snapshot_fds, write_diagnostic


@pytest.mark.asyncio
async def test_two_sources_cancel_caller_then_reset_real_transport(monkeypatch, request):
    phases = []
    writers = []
    second_started = asyncio.Event()

    async def serve(reader, writer):
        writers.append(writer)
        ordinal = len(writers)
        try:
            await reader.readuntil(b"\r\n\r\n")
            if ordinal == 1:
                phases.append("first_source_http_5xx")
                writer.write(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
            else:
                phases.append("second_source_response_wait")
                second_started.set()
                await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    baseline_sockets = {tuple(row["identity"]) for row in snapshot_fds().values()
                        if row["kind"] == "socket"}
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(host_resolver, "BILLING_API", f"http://127.0.0.1:{port}/primary/{{domain}}")
    monkeypatch.setattr(host_resolver, "BILLING_API_ALIAS", f"http://127.0.0.1:{port}/secondary/{{domain}}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    loop = asyncio.get_running_loop()
    caller = asyncio.create_task(host_resolver.resolve_vetmanager_host("fixture", max_retries=0))
    client = None
    new_sockets = set()
    try:
        await asyncio.wait_for(second_started.wait(), 5)
        assert len(writers) == 2
        new_sockets = {tuple(row["identity"]) for row in snapshot_fds().values()
                       if row["kind"] == "socket"} - baseline_sockets
        assert len(new_sockets) >= 3
        client = host_resolver._shared_clients_by_loop[loop]
        worker = host_resolver._inflight_resolutions_by_loop[loop]["fixture"]
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert not worker.done()
        phases.append("caller_cancelled_worker_pending")
        await host_resolver.reset_billing_resolver()
        phases.append("reset_succeeded")
        assert worker.done()
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
    remaining_sockets = {tuple(row["identity"]) for row in snapshot_fds().values()
                         if row["kind"] == "socket"}
    assert new_sockets.isdisjoint(remaining_sockets)
    gc.collect()
    collect_unraisable(request.config)
    phases.append("gc_unraisable_clean")
    evidence_dir = os.environ.get("STAGE459_OFFLINE_EVIDENCE_DIR")
    if evidence_dir:
        write_diagnostic(
            Path(evidence_dir) / "resolver-loopback.json",
            {"versions": {name: version(name) for name in ("anyio", "httpx", "httpcore", "uvloop")},
             "phases": phases, "connections_accepted": len(writers),
             "new_socket_count": len(new_sockets), "remaining_new_socket_count": 0,
             "reset_exception_group": False, "resource_warning": False,
             "client_closed": client.is_closed},
        )

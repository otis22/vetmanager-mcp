"""Regression checks using real pipes, child processes and a local HTTP socket."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import signal
import subprocess
import sys
import threading

import pytest

import host_resolver
from tests.live_test_lifecycle import assert_client_absent, assert_client_deleted, stop_processes
from vm_transport.pool import get_shared_http_client


@pytest.mark.parametrize("client", [[], {"merge_history": []}])
def test_absent_client_observed_shapes(client):
    assert_client_absent({"success": True, "data": {"totalCount": 0, "client": client}})


@pytest.mark.parametrize("client", [{"id": 7}, [{"id": 7}], {},
                                   {"merge_history": [7]}, {"merge_history": [], "id": 7}, None])
def test_absence_guard_rejects_records_and_unknown_shapes(client):
    with pytest.raises(AssertionError):
        assert_client_absent({"success": True, "data": {"totalCount": 0, "client": client}})


@pytest.mark.parametrize("success,total", [(False, 0), (True, 1), (None, 0)])
def test_absence_guard_requires_success_and_zero_count(success, total):
    with pytest.raises(AssertionError):
        assert_client_absent({"success": success, "data": {"totalCount": total, "client": []}})


@pytest.mark.parametrize("record", [{"id": 7, "status": "ACTIVE"},
                                   {"id": 8, "status": "DELETED"}, {}])
def test_delete_cleanup_rejects_active_or_another_record(record):
    with pytest.raises(AssertionError):
        assert_client_deleted({"success": True, "data": {"totalCount": 1, "client": record}}, 7)


def test_delete_cleanup_accepts_observed_soft_delete():
    assert_client_deleted({"success": True, "data": {
        "totalCount": 1, "client": {"id": 7, "status": "DELETED"}}}, 7)


@pytest.mark.parametrize("ignore_term", [False, True])
def test_live_child_is_reaped_and_pipes_closed(ignore_term):
    code = ("import signal,sys,time; "
            + ("signal.signal(signal.SIGTERM, signal.SIG_IGN); " if ignore_term else "")
            + "print('ready', flush=True); print('diagnostic', file=sys.stderr, flush=True); time.sleep(60)")
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline() == "ready\n"
        logs = stop_processes([child], timeout=.2)
        assert child.returncode == (-signal.SIGKILL if ignore_term else -signal.SIGTERM)
        assert child.stdout.closed and child.stderr.closed
        assert logs == ["diagnostic\n"]
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate()


@pytest.mark.parametrize("raise_in_callback", [False, True])
def test_run_async_closes_http_in_owning_loop(run_async, monkeypatch, raise_in_callback):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    monkeypatch.setenv("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS", "0.01")
    clients, close_loops = [], []
    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        async def probe():
            for client in (await get_shared_http_client(), await host_resolver._get_shared_client()):
                clients.append(client)
                original_close = client.aclose

                async def close(original_close=original_close):
                    close_loops.append(asyncio.get_running_loop().is_closed())
                    await original_close()

                monkeypatch.setattr(client, "aclose", close)
                response = await client.get(f"http://127.0.0.1:{server.server_port}")
                assert response.text == "ok"
            if raise_in_callback:
                raise ValueError("callback failed")

        try:
            if raise_in_callback:
                with pytest.raises(ValueError, match="callback failed"):
                    run_async(probe())
            else:
                run_async(probe())
            assert all(client.is_closed for client in clients)
            assert close_loops == [False, False]
        finally:
            server.shutdown()
            worker.join(timeout=5)

"""A failed local worker startup must not leave a subprocess behind."""

import httpx
import pytest

from tests import test_stage431_live


def test_stage431_failed_startup_reaps_worker(monkeypatch):
    class Process:
        def __init__(self):
            self.terminated = False
            self.waited = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            self.waited = True
            return 0

    process = Process()

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, path):
            raise httpx.ConnectError("local worker unavailable")

    monkeypatch.setattr(test_stage431_live.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(test_stage431_live.httpx, "Client", Client)
    monkeypatch.setattr(test_stage431_live.time, "sleep", lambda _: None)

    with pytest.raises(AssertionError, match="did not start"):
        test_stage431_live._start_worker(["worker"], ".", {}, "http://localhost")
    assert process.terminated and process.waited


def test_stage431_failed_readiness_reaps_started_worker(monkeypatch):
    class Process:
        def poll(self):
            return None

    process = Process()
    stopped = []
    monkeypatch.setenv("TEST_DOMAIN", "devtr6")
    monkeypatch.setattr(test_stage431_live, "seed_devtr6_bearer", lambda: "synthetic")
    monkeypatch.setattr(test_stage431_live, "_start_worker", lambda *args: process)
    monkeypatch.setattr(test_stage431_live, "_stop_worker", stopped.append)

    def fail_ready(_port):
        raise RuntimeError("local readiness failed")

    monkeypatch.setattr(test_stage431_live, "_stateless_protocol_ready", fail_ready)
    with pytest.raises(RuntimeError, match="local readiness failed"):
        test_stage431_live.test_devtr6_stateless_tool_survives_process_restart(None, 1)
    assert stopped == [process]

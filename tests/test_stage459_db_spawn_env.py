"""DB spawn children must not inherit pytest-only tracing before interpreter startup."""

import os
from pathlib import Path
import tracemalloc

import pytest

from tests.child_process_env import start_test_db_worker


ROOT = Path(__file__).resolve().parents[1]


class FakeProcess:
    def __init__(self, *, fails=False):
        self.fails = fails
        self.seen = None

    def start(self):
        self.seen = dict(os.environ)
        if self.fails:
            raise RuntimeError("synthetic spawn failure")


@pytest.mark.parametrize("fails", [False, True])
def test_db_spawn_removes_tracer_only_during_start_and_restores_parent(monkeypatch, fails):
    monkeypatch.setenv("PYTHONTRACEMALLOC", "5")
    monkeypatch.setenv("PYTHONWARNINGS", "error")
    monkeypatch.setenv("OTHER_TEST_FLAG", "same")
    process = FakeProcess(fails=fails)
    if fails:
        with pytest.raises(RuntimeError, match="synthetic spawn failure"):
            start_test_db_worker(process)
    else:
        start_test_db_worker(process)
    assert "PYTHONTRACEMALLOC" not in process.seen
    assert process.seen["PYTHONWARNINGS"] == "error"
    assert process.seen["OTHER_TEST_FLAG"] == "same"
    assert os.environ["PYTHONTRACEMALLOC"] == "5"
    assert os.environ["PYTHONWARNINGS"] == "error"


def test_parent_tracemalloc_engine_stays_active(monkeypatch):
    active_before = tracemalloc.is_tracing()
    if not active_before:
        tracemalloc.start(1)
    try:
        monkeypatch.setenv("PYTHONTRACEMALLOC", "5")
        start_test_db_worker(FakeProcess())
        assert tracemalloc.is_tracing()
    finally:
        if not active_before:
            tracemalloc.stop()


def test_connection_worker_uses_scoped_start_and_keeps_deadline():
    source = (ROOT / "tests/test_stage385_connection_live.py").read_text()
    assert "start_test_db_worker(process)" in source
    assert "signal.wait(10)" in source
    assert "process.start()" not in source


def test_production_environment_files_do_not_use_db_spawn_helper():
    for name in ("Dockerfile", "docker-compose.yml", "docker-compose.test.yml", "server.py"):
        assert "start_test_db_worker" not in (ROOT / name).read_text()

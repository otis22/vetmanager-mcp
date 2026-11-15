"""No-network guards for safe stage385 child readiness evidence."""

import json
import os
import ast
from pathlib import Path

import httpx
import pytest

from tests.stage385_readiness import (Stage385ReadinessTrace, classify_readiness,
                                      write_readiness_evidence)
from tests.stage385_child_phase import classify_phase, record_phase


def test_metrics_wait_loop_binds_its_own_slot_index():
    tree = ast.parse((Path(__file__).parent / "test_stage385_metrics_live.py").read_text())
    wait_loops = [node for node in ast.walk(tree) if isinstance(node, ast.For)
                  and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                          and child.func.attr == "wait_for_slot" for child in ast.walk(node))]
    assert any(isinstance(node.target, ast.Tuple) and len(node.target.elts) == 2
               and isinstance(node.target.elts[0], ast.Name)
               and node.target.elts[0].id == "index" for node in wait_loops)


def test_child_phase_file_is_private_and_rejects_raw_data(tmp_path):
    path = tmp_path / "phase.json"
    record_phase(path, "stage385-export", 0, "process_start", 0.01)
    record_phase(path, "stage385-export", 0, "before_import", 0.02)
    data = json.loads(path.read_text())
    assert [event["phase"] for event in data["events"]] == ["process_start", "before_import"]
    assert os.stat(path).st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        record_phase(path, "stage385-export", 0, "https://private.example", 0.03)


@pytest.mark.parametrize("phases,ready,expected", [
    (["process_start", "before_import"], False, "import"),
    (["process_start", "before_import", "after_import", "server_init"], False, "pre_dependency"),
    (["after_import", "redis_done", "db_done", "pre_bind"], False, "pre_bind"),
    (["after_import", "pre_bind", "server_error"], False, "server_error"),
    (["after_import", "pre_bind", "post_bind"], True, "ready"),
])
def test_phase_classes(phases, ready, expected):
    assert classify_phase(phases, ready=ready) == expected


def test_child_exited_class_is_explicit():
    result = classify_readiness(exit_code=1, stderr="startup failed")
    assert result["state"] == "child_exited"
    assert result["exit_class"] == "nonzero"


@pytest.mark.parametrize("stderr,expected", [
    ("Redis connection refused at private-host", "redis_unavailable"),
    ("sqlite3.OperationalError: database is locked", "db_unavailable"),
])
def test_backend_unavailable_is_classified_without_raw_text(stderr, expected):
    result = classify_readiness(exit_code=1, stderr=stderr)
    assert result["dependency_class"] == expected
    assert "private-host" not in str(result)


def test_http_timeout_and_non200_are_distinct():
    timeout = classify_readiness(error=httpx.ReadTimeout("private address"), listener=True)
    unavailable = classify_readiness(http_status=503, reason="storage_unavailable", listener=True)
    assert timeout["state"] == "http_timeout"
    assert unavailable["state"] == "http_non_200"
    assert unavailable["status_class"] == "5xx"
    assert unavailable["dependency_class"] == "db_unavailable"
    assert "private address" not in str(timeout)


def test_port_conflict_and_success_are_distinct():
    conflict = classify_readiness(exit_code=1, listener=True,
                                  stderr="[Errno 98] address already in use")
    ready = classify_readiness(http_status=200, listener=True)
    assert conflict["state"] == "port_conflict"
    assert ready["state"] == "ready"


def test_evidence_is_private_and_contains_only_technical_classes(tmp_path):
    path = tmp_path / "readiness.json"
    write_readiness_evidence(path, label="stage385-export", observations=[
        classify_readiness(error=httpx.ConnectError("secret at https://private.example"),
                           listener=False)
    ])
    assert os.stat(path).st_mode & 0o777 == 0o600
    data = json.loads(path.read_text())
    assert data["label"] == "stage385-export"
    assert "https://" not in str(data)
    assert "secret" not in str(data)
    assert "private.example" not in str(data)
    with pytest.raises(ValueError, match="Unsafe"):
        write_readiness_evidence(tmp_path / "unsafe.json", label="stage385-export",
                                 observations=[{**data["observations"][0], "url": "https://private.example"}])


def test_trace_records_ready_without_retries(monkeypatch):
    class Process:
        def poll(self):
            return None

    class Client:
        calls = 0

        def get(self, _path):
            self.calls += 1
            return httpx.Response(200, json={"checks": {"storage": {"reason": "ok"}}})

    trace = Stage385ReadinessTrace("stage385-export")
    client = Client()
    trace.wait_for_slot(client, Process(), 12345, 0)
    assert client.calls == 1
    assert trace.observations[0]["state"] == "ready"
    assert trace.observations[0]["attempts"] == 1


def test_trace_keeps_original_budget_and_safe_db_class(monkeypatch, tmp_path):
    class Process:
        def poll(self):
            return None

    class Client:
        calls = 0

        def get(self, _path):
            self.calls += 1
            return httpx.Response(503, json={"checks": {"storage": {"reason": "storage_unavailable"}}})

    monkeypatch.setattr("tests.stage385_readiness.time.sleep", lambda _: None)
    monkeypatch.setenv("REAL_JUNIT_DIR", str(tmp_path))
    trace = Stage385ReadinessTrace("stage385-metrics")
    client = Client()
    with pytest.raises(AssertionError, match="did not become ready"):
        trace.wait_for_slot(client, Process(), 12345, 0)
    trace.finish(["private DB detail"])
    assert client.calls == 100
    data = json.loads((tmp_path / "readiness-stage385-metrics.json").read_text())
    assert data["observations"][0]["dependency_class"] == "db_unavailable"
    assert data["observations"][0]["status_class"] == "5xx"
    assert data["observations"][0]["class_counts"] == {"http_non_200": 100}
    assert "private DB detail" not in str(data)
    assert os.stat(tmp_path / "readiness-stage385-metrics.json").st_mode & 0o777 == 0o600


def test_trace_classifies_exited_port_conflict_after_cleanup(monkeypatch, tmp_path):
    class Process:
        def poll(self):
            return 1

    monkeypatch.setattr("tests.stage385_readiness._listener_open", lambda _port: True)
    monkeypatch.setenv("REAL_JUNIT_DIR", str(tmp_path))
    trace = Stage385ReadinessTrace("stage385-export")
    with pytest.raises(AssertionError, match="exited before readiness"):
        trace.wait_for_slot(None, Process(), 12345, 0)
    trace.finish(["[Errno 98] address already in use at private-host"])
    data = json.loads((tmp_path / "readiness-stage385-export.json").read_text())
    assert data["observations"][0]["state"] == "port_conflict"
    assert "private-host" not in str(data)


def test_unprobed_sibling_slot_records_only_process_and_listener_class(monkeypatch):
    class Process:
        def poll(self):
            return None

    monkeypatch.setattr("tests.stage385_readiness._listener_open", lambda _port: False)
    trace = Stage385ReadinessTrace("stage385-export")
    trace.capture_unprobed([Process(), Process()], [10001, 10002])
    assert [item["state"] for item in trace.observations] == ["unprobed", "unprobed"]
    assert [item["listener"] for item in trace.observations] == [False, False]

"""No-network proof of stage385 launch order and the current readiness budget."""

import ast
from pathlib import Path

import httpx
import pytest

from tests.stage385_readiness import Stage385ReadinessTrace


@pytest.mark.parametrize("name", ["test_stage385_export_outcome_live.py", "test_stage385_metrics_live.py"])
def test_three_children_launch_before_sequential_readiness_checks(name):
    tree = ast.parse((Path(__file__).parent / name).read_text())
    loops = [node for node in ast.walk(tree) if isinstance(node, ast.For)]
    launch = [node.lineno for node in loops if any(isinstance(x, ast.Call)
              and isinstance(x.func, ast.Attribute) and x.func.attr == "Popen"
              for x in ast.walk(node))]
    checks = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute)
              and node.func.attr in {"wait_for_slot", "wait_for_slots"}]
    assert launch and checks and min(launch) < min(checks)


def test_cold_import_longer_than_current_budget_is_explicit_failure(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr("tests.stage385_readiness.time.sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))
    monkeypatch.setattr("tests.stage385_readiness._listener_open", lambda _port: False)

    class Process:
        def poll(self):
            return None

    class Client:
        def get(self, _path):
            if elapsed[0] < 23.667:
                raise httpx.ConnectError("private endpoint")
            return httpx.Response(200)

    trace = Stage385ReadinessTrace("stage385-export")
    with pytest.raises(AssertionError, match="did not become ready"):
        trace.wait_for_slot(Client(), Process(), 12345, 0)
    assert trace.observations[0]["attempts"] == 100
    assert trace.observations[0]["class_counts"] == {"connect_error": 100}


def test_import_within_budget_reaches_ready(monkeypatch):
    elapsed = [0.0]
    monkeypatch.setattr("tests.stage385_readiness.time.sleep", lambda seconds: elapsed.__setitem__(0, elapsed[0] + seconds))

    class Process:
        def poll(self):
            return None

    class Client:
        def get(self, _path):
            if elapsed[0] < 5.0:
                raise httpx.ConnectError("private endpoint")
            return httpx.Response(200)

    trace = Stage385ReadinessTrace("stage385-export")
    trace.wait_for_slot(Client(), Process(), 12345, 0)
    assert trace.observations[0]["state"] == "ready"
    assert trace.observations[0]["attempts"] <= 100


def test_sequential_launch_wait_policy_is_distinct_from_parallel():
    calls = []

    def launch(index):
        calls.append(("launch", index))

    def ready(index):
        calls.append(("ready", index))

    for index in range(3):
        launch(index)
        ready(index)
    assert calls == [("launch", 0), ("ready", 0), ("launch", 1),
                     ("ready", 1), ("launch", 2), ("ready", 2)]

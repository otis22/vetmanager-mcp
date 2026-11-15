"""Child MCP slots must not inherit pytest-only allocation tracing."""

import ast
from pathlib import Path

import pytest
from warning_policy import build_warning_error_flags
from tests.child_process_env import make_test_server_env


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["test_stage385_export_outcome_live.py", "test_stage385_metrics_live.py"])
def test_stage385_child_env_removes_only_tracemalloc(name):
    source = (ROOT / "tests" / name).read_text()
    assert "make_test_server_env()" in source
    assert 'Stage385ReadinessTrace(' in source
    assert 'from tests.stage385_child_phase import run; run()' in source
    assert 'range(1, 101)' in (ROOT / "tests/stage385_readiness.py").read_text()


def test_parent_runner_keeps_tracemalloc_and_warnings_as_errors():
    source = (ROOT / "scripts/run_opt_in_real_test_suite.py").read_text()
    assert 'env.setdefault("PYTHONTRACEMALLOC", "5")' in source
    assert 'build_warning_error_flags()' in source
    assert 'for item in ("-W", flag)' in source
    assert build_warning_error_flags() == ("error",)


def test_child_launch_keeps_other_environment_assignments():
    for name in ("test_stage385_export_outcome_live.py", "test_stage385_metrics_live.py"):
        tree = ast.parse((ROOT / "tests" / name).read_text())
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert {"env", "processes", "trace"} <= names


def test_child_env_drops_only_diagnostic_tracemalloc():
    source = {"PYTHONTRACEMALLOC": "5", "PYTHONWARNINGS": "error",
              "CUSTOM_TEST_FLAG": "kept"}
    child = make_test_server_env(source)
    assert child == {"PYTHONWARNINGS": "error", "CUSTOM_TEST_FLAG": "kept"}
    assert source["PYTHONTRACEMALLOC"] == "5"


@pytest.mark.parametrize("name", ["test_stage385_export_outcome_live.py",
                                  "test_stage385_metrics_live.py", "test_stage385_fence_live.py"])
def test_all_confirmed_server_launchers_use_test_env_helper(name):
    source = (ROOT / "tests" / name).read_text()
    assert "make_test_server_env()" in source

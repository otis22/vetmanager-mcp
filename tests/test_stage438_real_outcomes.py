"""A configured real contour must expose upstream failures as test failures."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from exceptions import AuthError, VetmanagerError
from tests import real_suite_outcomes as outcomes
from scripts.run_opt_in_real_test_suite import configuration_errors, contour_inventory, read_outcome
from scripts import run_opt_in_real_test_suite as real_runner
from tests.test_e2e_real import call


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [AuthError("synthetic auth failure"), VetmanagerError("synthetic network failure")])
async def test_configured_real_call_propagates_upstream_error(error):
    async def broken_call():
        raise error

    try:
        with pytest.raises(type(error), match="synthetic"):
            await call(broken_call())
    except pytest.skip.Exception:
        pytest.fail("A configured upstream failure was hidden as SKIP")


@pytest.mark.parametrize("env", [
    {"TEST_DOMAIN": "devtr6"},
    {"TEST_DOMAIN": "devtr6", "RUN_REAL_WEB_TESTS": "1"},
    {"RUN_REAL_BROWSER_TESTS": "1"},
    {"RUN_REAL_BROWSER_TESTS": "true"},
    {"TEST_USER_LOGIN": "someone"},
    {"STAGE385_REDIS_URL": "redis://unused"},
    {"STAGE385_REDIS_URL": "redis://unused", "STAGE385_PG_URL": "postgresql://unused",
     "STAGE385_PG_HOOK_DIR": "/tmp/unused"},
])
def test_partial_real_contour_configuration_fails(env):
    assert configuration_errors(env)
    assert configuration_errors({}) == []


def test_outcome_reader_rejects_empty_collection(tmp_path):
    report = tmp_path / "outcome.json"
    report.write_text(json.dumps({"collected": 0, "counts": {
        "passed": 0, "failed": 0, "skipped-not-configured": 0, "skipped-error": 0,
    }}))
    with pytest.raises(ValueError, match="empty"):
        read_outcome(report)
    report.write_text(json.dumps({"collected": 1, "counts": {
        "passed": 0, "failed": 0, "skipped-not-configured": 0, "skipped-error": 0,
    }}))
    with pytest.raises(ValueError, match="invalid"):
        read_outcome(report)


def test_inventory_names_live_and_dead_contours_without_values():
    inventory = contour_inventory({"TEST_DOMAIN": "devtr6", "TEST_API_KEY": "secret-sentinel"})
    assert inventory["api-key"] is True
    assert inventory["real-browser-api-key"] is False
    assert inventory["real-browser-user-token"] is False
    assert inventory["stage385-isolated"] is False
    assert "secret-sentinel" not in str(inventory)


def test_browser_api_key_flow_can_run_without_optional_user_token_credentials():
    env = {"TEST_DOMAIN": "devtr6", "TEST_API_KEY": "secret-sentinel", "RUN_REAL_BROWSER_TESTS": "1"}
    assert configuration_errors(env) == []
    inventory = contour_inventory(env)
    assert inventory["real-browser-api-key"] is True
    assert inventory["real-browser-user-token"] is False


def test_direct_user_token_contour_does_not_require_api_key():
    env = {"TEST_DOMAIN": "devtr6", "TEST_USER_TOKEN": "secret-sentinel"}
    assert configuration_errors(env) == []
    inventory = contour_inventory(env)
    assert inventory["api-key"] is False
    assert inventory["direct-user-token"] is True


def test_plugin_counts_only_matching_configuration_skip(monkeypatch):
    monkeypatch.setattr(outcomes, "_skipif_reasons", {"configured": set(), "absent": {"credentials absent"}})
    monkeypatch.setattr(outcomes, "_results", {})
    for nodeid in ("configured", "absent"):
        outcomes.pytest_runtest_logreport(SimpleNamespace(
            nodeid=nodeid, failed=False, passed=False, skipped=True,
            when="setup", longrepr=("file", 1, "Skipped: credentials absent"),
        ))
    assert outcomes._results == {"configured": "skipped-error", "absent": "skipped-not-configured"}


def test_plugin_teardown_failure_overrides_pass(monkeypatch):
    monkeypatch.setattr(outcomes, "_results", {})
    outcomes.pytest_runtest_logreport(SimpleNamespace(
        nodeid="real::test", failed=False, passed=True, skipped=False, when="call"))
    outcomes.pytest_runtest_logreport(SimpleNamespace(
        nodeid="real::test", failed=True, passed=False, skipped=False, when="teardown"))
    assert outcomes._results == {"real::test": "failed"}


def test_real_pytest_session_distinguishes_env_skip_from_runtime_skip(tmp_path):
    source = tmp_path / "test_optional.py"
    source.write_text('''import os
import pytest

@pytest.mark.skipif(not os.environ.get("STAGE438_OPTIONAL"), reason="optional env absent")
def test_optional():
    assert False

def test_runtime_skip():
    pytest.skip("upstream did not provide a candidate")
''')
    report = tmp_path / "outcome.json"
    env = dict(os.environ)
    env.pop("STAGE438_OPTIONAL", None)
    env["PYTEST_REAL_OUTCOME_FILE"] = str(report)
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "tests.real_suite_outcomes", str(source)],
        cwd=root, env=env, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stdout[-1000:]
    data = read_outcome(report)
    assert data["counts"] == {
        "passed": 0, "failed": 0, "skipped-not-configured": 1, "skipped-error": 1,
    }


@pytest.mark.parametrize("bad_group", [1, 2])
def test_runner_rejects_skip_error_in_either_group(monkeypatch, capsys, bad_group):
    monkeypatch.setattr(real_runner.os, "environ", {})
    calls = 0

    def fake_run(command, *, env, check):
        nonlocal calls
        calls += 1
        outcome = {"collected": 1, "counts": {
            "passed": int(calls != bad_group), "failed": 0,
            "skipped-not-configured": 0, "skipped-error": int(calls == bad_group),
        }, "not_configured": [], "skip_errors": ["synthetic::test"] if calls == bad_group else []}
        from pathlib import Path
        Path(env["PYTEST_REAL_OUTCOME_FILE"]).write_text(json.dumps(outcome))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(real_runner.subprocess, "run", fake_run)
    assert real_runner.main() == 1
    assert calls == 2
    output = capsys.readouterr().out
    assert "skipped-error=1" in output
    assert "skipped-error: synthetic::test" in output


@pytest.mark.parametrize("process_exit,write_report", [(0, False), (2, True)])
def test_runner_rejects_missing_report_and_abnormal_pytest_exit(monkeypatch, process_exit, write_report):
    monkeypatch.setattr(real_runner.os, "environ", {})

    def fake_run(command, *, env, check):
        if write_report:
            from pathlib import Path
            Path(env["PYTEST_REAL_OUTCOME_FILE"]).write_text(json.dumps({
                "collected": 1, "counts": {"passed": 1, "failed": 0,
                    "skipped-not-configured": 0, "skipped-error": 0},
                "not_configured": [], "skip_errors": [],
            }))
        return SimpleNamespace(returncode=process_exit)

    monkeypatch.setattr(real_runner.subprocess, "run", fake_run)
    assert real_runner.main() == 1

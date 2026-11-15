"""Export group contracts without calling the real API or creating an export."""

import ast
import asyncio
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import report_export_origin
from tests.export_shared import ExportStartOutcome, SharedExportRun, start_one_export
from tests import test_stage276_live_export_download as stage276


ROOT = Path(__file__).resolve().parent


def _source(name):
    return (ROOT / name).read_text()


def test_export_group_has_no_per_node_start_or_skip():
    """Both nodes must consume the one shared start, and guard refusal is red."""
    for name in ("test_stage276_live_export_download.py", "test_stage385_export_outcome_live.py"):
        tree = ast.parse(_source(name))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == "call_tool":
                assert not (node.args and isinstance(node.args[0], ast.Constant)
                            and node.args[0].value == "start_report_export")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "skip":
                assert not isinstance(node.func.value, ast.Name) or node.func.value.id != "pytest"
        assert '"name": "start_report_export"' not in _source(name)
    helper = ast.parse(_source("export_shared.py"))
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "skip"
        for node in ast.walk(helper)
    )


def test_export_manifest_orders_shared_start_before_poll_and_independent_metrics():
    manifest = json.loads((ROOT.parent / "scripts/real_group_manifest.json").read_text())
    nodes = manifest["groups"]["export"]
    assert nodes == [
        "tests/test_stage276_live_export_download.py::test_real_export_is_downloaded_cleaned_and_served_by_us",
        "tests/test_stage385_export_outcome_live.py::test_export_poll_success_is_one_outcome_across_slots",
        "tests/test_stage385_metrics_live.py::test_three_slots_export_one_devtr6_tool_count",
    ]
    assert "shared_live_export" not in _source("test_stage385_metrics_live.py")


def test_session_fixture_is_shared_between_two_modules(tmp_path):
    first = tmp_path / "test_a.py"
    second = tmp_path / "test_b.py"
    first.write_text('''pytest_plugins = ("tests.export_shared",)
from tests.export_shared import ExportStartOutcome
def test_first(shared_live_export):
    shared_live_export._outcome = ExportStartOutcome(17)
''')
    second.write_text('''pytest_plugins = ("tests.export_shared",)
def test_second(shared_live_export):
    assert shared_live_export.require_file_id() == 17
''')
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(first), str(second)],
        cwd=ROOT.parent, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, "Export session fixture was not shared across modules"


def test_one_start_yields_one_file_id_for_both_nodes():
    calls = []

    async def call(name, arguments):
        calls.append((name, arguments))
        return SimpleNamespace(is_error=False, structured_content={
            "data": {"report": {"report_file_id": 17}}
        })

    outcome = asyncio.run(start_one_export(call, 84))
    assert calls == [("start_report_export", {"report_id": 84})]
    assert outcome.require_file_id() == 17
    assert outcome.require_file_id() == 17
    assert len(calls) == 1


def test_group_fixture_reuses_first_start_in_one_running_loop():
    calls = []

    async def call(name, arguments):
        calls.append(name)
        return SimpleNamespace(is_error=False, structured_content={
            "data": {"report": {"report_file_id": 17}}
        })

    async def exercise():
        shared = SharedExportRun()
        assert (await shared.start_once(call, 84)).require_file_id() == 17
        assert (await shared.start_once(call, 84)).require_file_id() == 17
        assert shared.require_file_id() == 17

    asyncio.run(exercise())
    assert calls == ["start_report_export"]


def test_rate_limit_is_an_explicit_failure_without_response_body():
    async def call(_name, _arguments):
        raise RuntimeError("RUN_RATE_LIMITED: private upstream detail")

    outcome = asyncio.run(start_one_export(call, 84))
    assert outcome == ExportStartOutcome(None, "RUN_RATE_LIMITED")
    with pytest.raises(AssertionError, match="RUN_RATE_LIMITED") as error:
        outcome.require_file_id()
    assert "private upstream detail" not in str(error.value)


def test_download_and_poll_keep_separate_outcome_paths():
    stage276 = _source("test_stage276_live_export_download.py")
    stage385 = _source("test_stage385_export_outcome_live.py")
    assert '"get_report_export_download"' in stage276
    assert '"get_report_export_download"' in stage385
    assert "payload[\"depersonalized\"] is True" in stage276
    assert "_success_count(response.text)" in stage385
    assert "Shared export build did not finish" in stage276
    assert "Devtr6 export build did not finish" in stage385


@pytest.mark.asyncio
async def test_download_security_failure_remains_its_own_failure(monkeypatch, tmp_path):
    shared = SharedExportRun()
    shared._outcome = ExportStartOutcome(17)
    monkeypatch.setattr(stage276, "patch_runtime_credentials",
                        lambda *_args, **_kwargs: (nullcontext(), nullcontext()))

    async def refuse(name, _arguments):
        assert name == "get_report_export_download"
        raise RuntimeError("The export storage address was rejected by MCP security policy.")

    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(stage276.mcp, "call_tool", refuse)
    monkeypatch.setattr(stage276.asyncio, "sleep", no_wait)
    with pytest.raises(RuntimeError, match="security policy"):
        await stage276.test_real_export_is_downloaded_cleaned_and_served_by_us(tmp_path, shared)


@pytest.fixture
def safe_storage_locator(monkeypatch):
    """Synthetic HTTPS storage shape; no real hostname or export is used."""
    monkeypatch.setenv("REPORT_EXPORT_ALLOWED_ORIGINS", "https://storage.example")

    async def resolver(_hostname):
        return ("93.184.216.34",)

    return "https://storage.example/report.csv?opaque=redacted", resolver


@pytest.mark.asyncio
async def test_safe_storage_shape_and_wrong_host_policy(safe_storage_locator):
    locator, resolver = safe_storage_locator
    target = await report_export_origin.resolve_export_target(locator, resolver=resolver)
    assert target.origin == "https://storage.example"
    assert target.addresses == ("93.184.216.34",)
    wrong = locator.replace("storage.example", "untrusted.example")
    with pytest.raises(Exception) as error:
        await report_export_origin.resolve_export_target(wrong, resolver=resolver)
    assert "allowlist" in str(error.value)
    assert "opaque" not in str(error.value)

"""Nightly CI must fail closed and publish only static, sanitized evidence."""

import json
import os
from pathlib import Path
import subprocess
from subprocess import CompletedProcess
from xml.etree import ElementTree as ET

import pytest
import yaml

from scripts import nightly_regression as nightly
from scripts.run_isolated_test_suite import group_image_build_required


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("missing", [None, "TEST_DOMAIN", "TEST_API_KEY", "image"])
def test_api_key_only_nightly_preflight(missing):
    env = {"TEST_DOMAIN": "synthetic", "TEST_API_KEY": "synthetic"}
    image = "sha256:" + "a" * 64
    if missing == "image":
        image = ""
    elif missing:
        env.pop(missing)
    assert bool(nightly.preflight_errors(env, image)) == (missing is not None)


def test_auth_plan_accounts_for_optional_nodes_without_dropping_api_groups():
    from scripts.real_group_gate import configured_manifest
    manifest = json.loads((ROOT / "scripts/real_group_manifest.json").read_text())
    selected, unavailable = configured_manifest(manifest, {})
    assert set(selected["groups"]) == set(manifest["groups"])
    assert selected["groups"]["write-restore"] == manifest["groups"]["write-restore"]
    assert len(unavailable) == 6
    configured = {node for nodes in selected["groups"].values() for node in nodes}
    original = {node for nodes in manifest["groups"].values() for node in nodes}
    assert configured.isdisjoint(unavailable)
    assert configured | set(unavailable) == original
    full, unavailable = configured_manifest(manifest, {"TEST_USER_LOGIN": "synthetic",
                                                      "TEST_USER_PASSWORD": "synthetic"})
    assert full["groups"] == manifest["groups"] and unavailable == {}


def test_auth_plan_rejects_partial_login_and_untrusted_exclusions():
    from scripts.real_group_gate import configured_manifest
    manifest = json.loads((ROOT / "scripts/real_group_manifest.json").read_text())
    with pytest.raises(ValueError):
        configured_manifest(manifest, {"TEST_USER_LOGIN": "synthetic"})
    node = manifest["required_nodes"][0]
    manifest.setdefault("auth_requirements", {})[node] = "login-password"
    with pytest.raises(ValueError):
        configured_manifest(manifest, {})


@pytest.mark.parametrize("token", ["", "synthetic-configured-token"])
def test_workflow_empty_optional_token_does_not_override_generated_auth(tmp_path, token):
    workflow = yaml.safe_load((ROOT / ".github/workflows/nightly.yml").read_text())
    step = next(step for step in workflow["jobs"]["nightly"]["steps"]
                if step.get("name") == "Full regression")
    probe = tmp_path / "python3"
    probe.write_text('#!/bin/sh\nif [ "$EXPECT_TOKEN" = absent ]; then\n'
                     '  test "${TEST_USER_TOKEN+x}" != x\nelse\n'
                     '  test "$TEST_USER_TOKEN" = "$EXPECT_TOKEN"\nfi\n')
    probe.chmod(0o700)
    env = dict(os.environ, TEST_USER_TOKEN=token, EXPECT_TOKEN=token or "absent",
               PATH=str(tmp_path) + os.pathsep + os.environ["PATH"],
               RUNNER_TEMP=str(tmp_path), GITHUB_RUN_ID="1", GITHUB_RUN_ATTEMPT="1")
    result = subprocess.run(["bash", "-e", "-c", step["run"]], env=env, capture_output=True)
    assert result.returncode == 0


def test_workflow_schedule_main_serialization_and_single_build():
    workflow = yaml.safe_load((ROOT / ".github/workflows/nightly.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["schedule"] == [{"cron": "17 23 * * *"}]
    assert "workflow_dispatch" in triggers
    job = workflow["jobs"]["nightly"]
    assert "refs/heads/main" in job["if"]
    assert "ref-check" in job["needs"]
    assert "exit 1" in workflow["jobs"]["ref-check"]["steps"][0]["run"]
    assert workflow["concurrency"]["group"] == "devtr6-real"
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert yaml.safe_load((ROOT / ".github/workflows/test-real.yml").read_text())["concurrency"]["group"] == "devtr6-real"
    steps = job["steps"]
    builds = [step for step in steps if "docker build " in step.get("run", "")]
    assert len(builds) == 1
    assert any(step.get("uses", "").startswith("actions/upload-artifact@")
               and step.get("if") == "${{ always() }}" for step in steps)


def test_failed_write_or_cleanup_blocks_later_upstream():
    assert nightly.blocks_upstream("write-restore", 1, {"results": {"real-group": 1, "cleanup": 0}})
    assert nightly.blocks_upstream("read", 1, {"results": {"real-group": 1, "cleanup": 1}})
    assert nightly.blocks_upstream("read", 0, None)
    assert nightly.blocks_upstream("read", 1, {"results": {"real-group": 1, "cleanup": 0}},
                                   evidence_complete=False)
    assert not nightly.blocks_upstream("read", 1, {"results": {"real-group": 1, "cleanup": 0}})


def test_prebuilt_image_marker_prevents_second_build(tmp_path):
    (tmp_path / "test-image.id").write_text("sha256:" + "a" * 64 + "\n")
    assert group_image_build_required(tmp_path, requested=False) is False


def test_image_id_change_is_rejected(monkeypatch):
    monkeypatch.setattr(nightly.subprocess, "run", lambda *a, **k: CompletedProcess(a, 0, "sha256:new\n"))
    assert not nightly.same_image("sha256:old")
    assert nightly.same_image("sha256:new")


def test_evidence_name_uses_longest_group_prefix():
    assert nightly.group_from_evidence("report-ai-420-abc", {"report-ai": [], "report-ai-420": []}) == "report-ai-420"


def test_aggregate_cannot_mask_failed_required_group():
    assert nightly.final_exit({"default": 0, "postgres": 0, "read": 1}, aggregate=0) == 1
    assert nightly.final_exit({"default": 0, "postgres": 0, "read": 0}, aggregate=1) == 1
    assert nightly.final_exit({"default": 0, "postgres": 0, "read": 0}, aggregate=0) == 0
    assert nightly.final_exit({"default": 0, "postgres": 0}, aggregate=0,
                              required={"default", "postgres", "read"}) == 1


def test_sanitized_junit_discards_sensitive_output_and_rejects_unknown_node(tmp_path):
    source = tmp_path / "raw.xml"
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    case = ET.SubElement(suite, "testcase", classname="tests.test_example", name="test_a")
    ET.SubElement(case, "failure", message="clinic secret").text = "patient name"
    ET.SubElement(case, "system-out").text = "test token"
    ET.ElementTree(root).write(source)
    output = tmp_path / "safe.xml"
    nightly.sanitize_junit(source, output, {"tests/test_example.py::test_a"})
    safe = output.read_text()
    assert "clinic secret" not in safe and "patient name" not in safe and "test token" not in safe
    assert "test_a" in safe and "failure" in safe
    with pytest.raises(ValueError):
        nightly.sanitize_junit(source, output, {"tests/test_other.py::test_a"})
    with pytest.raises(ValueError):
        nightly.sanitize_junit(source, output, {"tests/test_example.py::test_a",
                                                "tests/test_example.py::test_b"})
    ET.SubElement(suite, "testcase", classname="tests.test_example", name="test_b")
    ET.ElementTree(root).write(source)
    with pytest.raises(ValueError):
        nightly.sanitize_junit(source, output, {"tests/test_example.py::test_a"})


def test_parametrized_ipv6_node_keeps_colons_inside_parameter(tmp_path):
    source = tmp_path / "raw.xml"
    root = ET.Element("testsuite")
    ET.SubElement(root, "testcase", classname="tests.test_example", name="test_host[::1]")
    ET.ElementTree(root).write(source)
    nightly.sanitize_junit(source, tmp_path / "safe.xml", {"tests/test_example.py::test_host[::1]"})


def test_sanitized_outcome_rejects_unlisted_node_and_strips_extra(tmp_path):
    raw = tmp_path / "raw.json"
    raw.write_text(json.dumps({"collected": 1, "counts": {"passed": 1, "failed": 0,
        "skipped-not-configured": 0, "skipped-error": 0},
        "nodes": {"tests/test_example.py::test_a": "passed"}, "secret": "token"}))
    target = tmp_path / "safe.json"
    nightly.sanitize_outcome(raw, target, {"tests/test_example.py::test_a"})
    assert "token" not in target.read_text()
    with pytest.raises(ValueError):
        nightly.sanitize_outcome(raw, target, {"tests/test_other.py::test_a"})


def test_truncated_group_evidence_blocks_later_upstream(tmp_path):
    node = "tests/test_example.py::test_a"
    (tmp_path / "shard.json").write_text(json.dumps({"group": "read", "nodes": [node],
        "image_id": "sha256:old", "results": {"test": 1, "cleanup": 0}}))
    (tmp_path / "read.outcome.json").write_text(json.dumps({"collected": 1,
        "nodes": {node: "failed"}, "counts": {"passed": 0, "failed": 1,
        "skipped-not-configured": 0, "skipped-error": 0}}))
    (tmp_path / "read.xml").write_text("<truncated>")
    assert not nightly.group_evidence_complete(tmp_path, "read", {node}, "sha256:old", 1)


def test_group_outcome_must_match_junit_failure(tmp_path):
    node = "tests/test_example.py::test_a"
    (tmp_path / "shard.json").write_text(json.dumps({"group": "read", "nodes": [node],
        "image_id": "sha256:old", "results": {"test": 1, "cleanup": 0}}))
    (tmp_path / "read.outcome.json").write_text(json.dumps({"collected": 1,
        "nodes": {node: "failed"}, "counts": {"passed": 0, "failed": 1,
        "skipped-not-configured": 0, "skipped-error": 0}}))
    (tmp_path / "read.xml").write_text('<testsuite><testcase classname="tests.test_example" name="test_a"/></testsuite>')
    assert not nightly.group_evidence_complete(tmp_path, "read", {node}, "sha256:old", 1)


def test_offline_cleanup_must_be_confirmed_before_live(tmp_path):
    (tmp_path / "summary.json").write_text(json.dumps({"results": {"default": 0, "cleanup": 1}}))
    (tmp_path / "cleanup.log").write_text("cleanup failed")
    assert not nightly.offline_cleanup_ok(tmp_path)
    (tmp_path / "summary.json").write_text(json.dumps({"results": {"default": 1, "cleanup": 0}}))
    assert nightly.offline_cleanup_ok(tmp_path)


def test_successful_group_requires_artifact_evidence_directory(tmp_path):
    groups = {"read": [], "read-extra": []}
    assert not nightly.group_artifact_source(tmp_path, "read", groups)
    (tmp_path / "read-abc").mkdir()
    assert nightly.group_artifact_source(tmp_path, "read", groups) == tmp_path / "read-abc"
    (tmp_path / "read-extra-abc").mkdir()
    assert nightly.group_artifact_source(tmp_path, "read", groups) == tmp_path / "read-abc"
    (tmp_path / "read-def").mkdir()
    assert not nightly.group_artifact_source(tmp_path, "read", groups)


def test_auth_map_matches_existing_user_auth_guards():
    """New user-auth skips must be explicitly accounted for, not silently lost."""
    import ast
    expected = {}
    decorators = {"skip_if_no_user_login_flow": "login-password",
                  "skip_if_no_real_user_token_flow": "login-password",
                  "skip_if_no_user_token": "user-token"}
    for file in ("tests/test_e2e_real.py", "tests/test_browser_real_opt_in.py"):
        tree = ast.parse((ROOT / file).read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Name) and decorator.id in decorators:
                        expected[f"{file}::{node.name}"] = decorators[decorator.id]
    manifest = json.loads((ROOT / "scripts/real_group_manifest.json").read_text())
    assert manifest.get("auth_requirements") == expected


def test_group_auth_preparation_keeps_nongroup_contract():
    from scripts.run_isolated_test_suite import required_auth_flags
    assert required_auth_flags("real", "auth-web") == ["--require-api"]
    assert required_auth_flags("real", None) == ["--require-all"]
    assert required_auth_flags("all", None) == ["--require-all"]
    assert required_auth_flags("recovery", None) == ["--require-api"]


def test_group_auth_selection_uses_compose_effective_environment(monkeypatch, tmp_path, capsys):
    from scripts.run_isolated_test_suite import resolved_group_environment
    path = tmp_path / "synthetic.env"
    path.write_text("TEST_USER_LOGIN=synthetic\nTEST_USER_PASSWORD=synthetic\n")
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(command, 0, json.dumps({"services": {"test": {
            "environment": {"TEST_DOMAIN": "synthetic", "TEST_API_KEY": "synthetic",
                            "TEST_USER_LOGIN": "synthetic", "TEST_USER_PASSWORD": "synthetic"}}}}))
    monkeypatch.setattr(subprocess, "run", run)
    result = resolved_group_environment([str(path)])
    assert result["TEST_USER_LOGIN"] == "synthetic"
    command, kwargs = calls[0]
    assert command[-3:] == ["config", "--format", "json"]
    assert str(path.resolve()) in command
    assert kwargs["capture_output"] and kwargs["text"]
    assert not capsys.readouterr().out


def test_nightly_api_only_reaches_inventory(monkeypatch, tmp_path):
    env = {"TEST_DOMAIN": "synthetic", "TEST_API_KEY": "synthetic"}
    monkeypatch.setattr(nightly, "resolved_group_environment", lambda paths: env)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: CompletedProcess(a, 0, "sha256:" + "a" * 64))
    monkeypatch.setattr("sys.argv", ["nightly", "--evidence-dir", str(tmp_path / "evidence")])
    calls = []
    monkeypatch.setattr(nightly, "run_command", lambda name, *a: calls.append(name) or 1)
    assert nightly.main() == 1  # intentional inventory failure, no real execution
    assert calls == ["inventory"]
    summary = json.loads((tmp_path / "evidence/artifact/summary.json").read_text())
    assert len(summary["not_configured"]) == 6
    assert summary["configured_nodes"] == 132


def test_direct_token_enables_only_its_existing_optional_node():
    from scripts.real_group_gate import configured_manifest, manifest_hash
    manifest = json.loads((ROOT / "scripts/real_group_manifest.json").read_text())
    api, _ = configured_manifest(manifest, {})
    direct, unavailable = configured_manifest(manifest, {"TEST_USER_TOKEN": "synthetic"})
    assert len(unavailable) == 5
    assert manifest_hash(api) != manifest_hash(direct)
    assert all(reason == "login-password" for reason in unavailable.values())


@pytest.mark.asyncio
async def test_prepare_derives_token_and_base_url_before_execution(tmp_path, monkeypatch, capsys):
    from scripts import prepare_real_test_auth as auth
    monkeypatch.setenv("TEST_DOMAIN", "synthetic")
    monkeypatch.setenv("TEST_API_KEY", "synthetic")
    monkeypatch.setenv("TEST_USER_LOGIN", "synthetic")
    monkeypatch.setenv("TEST_USER_PASSWORD", "synthetic")
    monkeypatch.delenv("TEST_USER_TOKEN", raising=False)
    async def exchange(*args, **kwargs):
        return "https://synthetic.invalid", "synthetic-derived-token"
    monkeypatch.setattr(auth, "exchange_user_token", exchange)
    path = tmp_path / "auth.env"
    await auth.prepare(path, require_api=True)
    assert path.read_text() == ("TEST_USER_TOKEN=synthetic-derived-token\n"
                                "TEST_USER_TOKEN_BASE_URL=https://synthetic.invalid\n")
    assert "synthetic-derived-token" not in capsys.readouterr().out

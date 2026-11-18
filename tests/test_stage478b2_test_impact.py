"""Stage 478B-2: fail-closed PR impact and split-node evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
import yaml

from scripts import ci_test_impact as impact
from scripts import split_default_gate as split


ROOT = Path(__file__).resolve().parents[1]
FAST = ["tests/test_fast.py::test_a", "tests/test_fast.py::test_b"]
FULL = [*FAST, "tests/test_slow.py::test_c"]


def write_map(root: Path, payload: dict | None = None) -> None:
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "test_impact_map.json").write_text(json.dumps(payload or {
        "schema_version": 1,
        "isolated": {"tools/whoami.py": {"owners": ["tests/test_fast.py"], "postgres": False}},
    }))
    (scripts / "default_node_inventory.json").write_text(json.dumps({
        "tests/test_fast.py": {"count": 2, "sha256": "0" * 64},
        "tests/test_slow.py": {"count": 1, "sha256": "0" * 64},
    }))


def test_isolated_tool_selects_only_fast_and_owning_nodes(tmp_path):
    write_map(tmp_path)
    plan = impact.select_plan([("M", "tools/whoami.py")], tmp_path)
    assert plan == {"mode": "isolated", "owners": ["tests/test_fast.py"],
                    "postgres": False, "reason": "mapped isolated files"}
    assert split.partition(FULL, FAST, plan) == (FAST, [])


def test_isolated_tool_with_existing_owning_test_stays_narrow(tmp_path):
    write_map(tmp_path)
    plan = impact.select_plan([("M", "tools/whoami.py"), ("M", "tests/test_fast.py")], tmp_path)
    assert plan["mode"] == "isolated"
    assert plan["owners"] == ["tests/test_fast.py"]
    assert impact.select_plan([("M", "tools/whoami.py"), ("A", "tests/test_fast.py")], tmp_path)["mode"] == "full"
    assert impact.select_plan([("M", "tools/whoami.py"), ("M", "tests/test_new.py")], tmp_path)["mode"] == "full"


@pytest.mark.parametrize("change", [
    [("M", "test_contours.py")], [("M", "tests/test_fast.py")],
    [("M", "scripts/test_impact_map.json")], [("M", ".github/workflows/test.yml")],
    [("M", "tools/unknown.py")], [("R100", "tools/whoami.py")],
    [("M", "tools/whoami.py"), ("M", "tools/unknown.py")],
])
def test_shared_unknown_or_ambiguous_is_full(tmp_path, change):
    write_map(tmp_path)
    plan = impact.select_plan(change, tmp_path)
    assert plan["mode"] == "full" and plan["postgres"] is True
    assert split.partition(FULL, FAST, plan) == (FAST, [FULL[-1]])


@pytest.mark.parametrize("bad", [
    "not json", "{}", '{"schema_version":2,"isolated":{}}',
    '{"schema_version":1,"isolated":{"tools/whoami.py":{"owners":[],"postgres":false}}}',
    '{"schema_version":1,"isolated":{"scripts/test_impact_map.json":{"owners":["tests/test_fast.py"],"postgres":false}}}',
])
def test_invalid_map_falls_back_to_full(tmp_path, bad):
    write_map(tmp_path)
    (tmp_path / "scripts/test_impact_map.json").write_text(bad)
    assert impact.select_plan([("M", "tools/whoami.py")], tmp_path)["mode"] == "full"


def test_nonfast_owning_node_and_pg_selection(tmp_path):
    write_map(tmp_path, {"schema_version": 1, "isolated": {
        "tools/slow.py": {"owners": ["tests/test_slow.py"], "postgres": True}}})
    plan = impact.select_plan([("M", "tools/slow.py")], tmp_path)
    assert plan["postgres"] is True
    assert split.partition(FULL, FAST, plan) == (FAST, [FULL[-1]])


def test_map_owner_missing_from_inventory_falls_back_to_full(tmp_path):
    write_map(tmp_path, {"schema_version": 1, "isolated": {
        "tools/whoami.py": {"owners": ["tests/test_missing.py"], "postgres": False}}})
    assert impact.select_plan([("M", "tools/whoami.py")], tmp_path)["mode"] == "full"


def junit(path: Path, nodes: list[str], *, skip: bool = False):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    for node in nodes:
        file, name = node.split("::")
        case = ET.SubElement(suite, "testcase", classname=file[:-3].replace("/", "."), name=name)
        if skip:
            ET.SubElement(case, "skipped")
    ET.ElementTree(root).write(path)


def test_aggregate_accepts_exact_split_and_empty_remainder(tmp_path):
    fast, slow = tmp_path / "fast.xml", tmp_path / "slow.xml"
    junit(fast, FAST)
    junit(slow, [FULL[-1]])
    split.validate_union(FULL, FAST, [FULL[-1]], fast, slow)
    split.validate_union(FAST, FAST, [], fast, None)


@pytest.mark.parametrize("mutation", ["lost", "duplicate", "skip", "wrong_partition"])
def test_aggregate_rejects_lost_duplicate_skip_or_wrong_partition(tmp_path, mutation):
    fast, slow = tmp_path / "fast.xml", tmp_path / "slow.xml"
    junit(fast, FAST if mutation != "lost" else FAST[:1], skip=mutation == "skip")
    junit(slow, [FAST[0]] if mutation in ("duplicate", "wrong_partition") else [FULL[-1]])
    with pytest.raises(ValueError):
        split.validate_union(FULL, FAST, [FULL[-1]], fast, slow)


def test_mutating_protected_selector_cannot_narrow_map(tmp_path):
    write_map(tmp_path, {"schema_version": 1, "isolated": {
        "scripts/ci_test_impact.py": {"owners": ["tests/test_fast.py"], "postgres": False}}})
    assert impact.select_plan([("M", "scripts/ci_test_impact.py")], tmp_path)["mode"] == "full"


def test_fast_shards_cover_every_node_once_and_keep_file_ownership():
    nodes = [*FAST, FULL[-1], "tests/test_slow.py::test_d"]
    shards = split.shard_fast_nodes(nodes, 3)
    assert len(shards) == 3
    assert sorted(node for shard in shards for node in shard) == sorted(nodes)
    assert len({node for shard in shards for node in shard}) == len(nodes)
    assert sum(bool(set(shard) & set(FAST)) for shard in shards) == 1
    assert sum(bool(set(shard) & {FULL[-1], "tests/test_slow.py::test_d"}) for shard in shards) == 1


def test_measured_expensive_fast_files_get_clean_processes():
    regular = ["tests/test_other.py::test_one", "tests/test_other.py::test_two"]
    env = ["tests/test_stage285_runtime_env_reaches_container.py::test_one"]
    hint = ["tests/test_stage337_user_name_search_hint.py::test_two"]
    scanner = ["tests/test_stage459_server_child_inventory.py::test_one"]
    tls = ["tests/test_stage459_resolver_tls_loopback.py::test_one"]
    heavy = ["tests/test_stage384_retuning.py::test_one",
             "tests/test_stage111_blocker_cleanup.py::test_one"]
    balance = ["tests/test_stage159_feedback_product_metrics.py::test_one",
               "tests/test_stage389_inactive_pets_cursor.py::test_one"]
    nodes = regular + env + hint + scanner + tls + heavy + balance
    shards = split.ci_fast_shards(nodes)
    assert len(shards) == 12
    assert sorted(node for shard in shards for node in shard) == sorted(nodes)
    assert len({node for shard in shards for node in shard}) == len(nodes)
    assert shards[8] == env and shards[9] == hint
    assert shards[10] == scanner and shards[11] == tls
    assert all(not (set(shard) & set(env + hint + scanner)) for shard in shards[:8])
    assert set(heavy) <= set(shards[2])
    assert balance[0] in shards[4]
    assert balance[1] in shards[7]
    with pytest.raises(ValueError, match="missing fast shard file"):
        split.ci_fast_shards([node for node in nodes if node != balance[0]])


def test_ci_wires_exact_aggregate_and_main_full_boundary():
    jobs = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())["jobs"]
    from scripts import run_fast_test_suite as fast_runner
    assert jobs["fast"]["strategy"]["matrix"]["shard"] == list(range(fast_runner.SHARD_COUNT))
    assert fast_runner.SHARD_COUNT == 12
    assert "inventory-preflight" in jobs["fast"]["needs"]
    assert "--ci-shard-index" in str(jobs["fast"])
    steps = jobs["fast"]["steps"]
    run = next(step for step in steps if step.get("name") == "Run fast contour")
    upload = next(step for step in steps if step.get("name") == "Upload fast evidence")
    assert run["id"] == "fast" and 'tests_passed=true' in run["run"]
    assert "steps.fast.outputs.tests_passed == 'true'" in upload["if"]
    assert "always()" in upload["if"]
    assert "elapsed > 180" in run["run"]
    assert jobs["fast-aggregate"]["needs"] == ["scope-and-reuse", "build-image",
                                                "inventory-preflight", "fast"]
    assert "--ci-aggregate-parts" in str(jobs["fast-aggregate"])
    assert "fast-aggregate" in jobs["default"]["needs"]
    assert "run_split_default_suite.py" in str(jobs["default"])
    assert "run_postgres == 'true'" in jobs["postgres-activation-telemetry"]["if"]
    assert "full_plan == 'true'" in jobs["validated-tree"]["if"]
    assert "github.event_name == 'pull_request'" in jobs["validated-tree"]["if"]


def test_super_review_includes_test_contours_role_and_aggregation():
    for path in (".codex/skills/super-review/SKILL.md", ".claude/commands/super-review.md",
                 ".claude/agents/reviewer-aggregator.md", "CLAUDE.md"):
        assert "test-contours" in (ROOT / path).read_text(), path
    brief = (ROOT / ".claude/agents/reviewer-test-contours.md").read_text()
    for required in ("fail", "node", "skip", "PR/main/nightly", "fingerprint"):
        assert required in brief


def test_isolated_runner_rejects_partition_mutation_losing_owning_node(tmp_path, monkeypatch):
    from coverage import CoverageData
    from scripts import run_split_default_suite as runner
    import subprocess

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_FILE", str(tmp_path / ".coverage.aggregate-output"))
    if "COV_CORE_DATAFILE" in os.environ:
        monkeypatch.setenv("COV_CORE_DATAFILE", str(tmp_path / ".coverage.subprocess"))
    fast_dir = tmp_path / "fast"
    fast_dir.mkdir()
    junit(fast_dir / "fast.xml", FAST)
    (fast_dir / "fingerprint.txt").write_text("same\n")
    product = tmp_path / "product.py"
    product.write_text("value = 1\n")
    data = CoverageData(basename=str(fast_dir / ".coverage.fast"))
    data.add_lines({str(product): {1}})
    data.write()
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"mode": "isolated", "owners": ["tests/test_slow.py"],
                                "postgres": False, "reason": "mutation guard"}))
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "check_inventory", lambda _: FULL)
    monkeypatch.setattr(runner, "collected_fast_nodes", lambda: FAST)
    monkeypatch.setattr(runner, "source_fingerprint", lambda: "same")
    monkeypatch.setattr(runner, "partition", lambda *args: (FAST, []))
    real_run = subprocess.run

    def run(command, **kwargs):
        if any("check_known_issue_tool_names.py" in arg for arg in command):
            return subprocess.CompletedProcess(command, 0)
        return real_run(command, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", run)
    with pytest.raises(ValueError, match="owning"):
        runner.run(plan, fast_dir)
    assert not (tmp_path / ".stage465-default-gate.json").exists()


@pytest.mark.parametrize("runner", ["fast", "default"])
def test_aggregate_rejects_corrupt_coverage_even_with_valid_peer(tmp_path, monkeypatch, runner):
    """Coverage CLI otherwise warns, skips the corrupt peer and exits zero."""
    from coverage import CoverageData
    from scripts import run_fast_test_suite as fast_runner
    from scripts import run_split_default_suite as default_runner
    import subprocess

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COVERAGE_FILE", str(tmp_path / ".coverage.aggregate-output"))
    if "COV_CORE_DATAFILE" in os.environ:
        monkeypatch.setenv("COV_CORE_DATAFILE", str(tmp_path / ".coverage.subprocess"))

    def valid_coverage(path):
        data = CoverageData(basename=str(path))
        data.add_lines({str(tmp_path / "product.py"): {1}})
        data.write()

    (tmp_path / "product.py").write_text("value = 1\n")
    if runner == "fast":
        parts = tmp_path / "parts"
        for index, node in enumerate(FAST):
            part = parts / f"ci-fast-shard-{index}"
            part.mkdir(parents=True)
            junit(part / f"shard-{index}.xml", [node])
            (part / f"fingerprint-{index}.txt").write_text("same\n")
            coverage = part / f".coverage.shard-{index}"
            valid_coverage(coverage) if index == 0 else coverage.write_text("corrupt")
        monkeypatch.setattr(fast_runner, "check_inventory", lambda _: FAST)
        monkeypatch.setattr(fast_runner, "source_fingerprint", lambda: "same")
        monkeypatch.setattr(fast_runner, "collected_fast_nodes", lambda: FAST)
        monkeypatch.setattr(fast_runner, "ci_fast_shards", lambda _: [[n] for n in FAST])
        monkeypatch.setattr(fast_runner, "SHARD_COUNT", len(FAST))
        (parts / "ci-fast-shard-2").mkdir()
        with pytest.raises(ValueError, match="unexpected fast shard"):
            fast_runner.aggregate_ci_shards(parts, tmp_path / "out")
        (parts / "ci-fast-shard-2").rmdir()
        with pytest.raises(ValueError, match="coverage"):
            fast_runner.aggregate_ci_shards(parts, tmp_path / "out")
    else:
        fast_dir = tmp_path / "fast"
        fast_dir.mkdir()
        junit(fast_dir / "fast.xml", FAST)
        (fast_dir / "fingerprint.txt").write_text("same\n")
        valid_coverage(fast_dir / ".coverage.fast")
        plan = tmp_path / "plan.json"
        plan.write_text(json.dumps({"mode": "full", "owners": [], "postgres": True, "reason": "guard"}))
        real_run = subprocess.run

        def run(command, **kwargs):
            if "pytest" in command:
                junit(tmp_path / "ci-default-evidence/remainder.xml", [FULL[-1]])
                (tmp_path / "ci-default-evidence/.coverage.remainder").write_text("corrupt")
                return subprocess.CompletedProcess(command, 0)
            if any("check_known_issue_tool_names.py" in arg for arg in command):
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        monkeypatch.setattr(default_runner, "ROOT", tmp_path)
        monkeypatch.setattr(default_runner, "check_inventory", lambda _: FULL)
        monkeypatch.setattr(default_runner, "collected_fast_nodes", lambda: FAST)
        monkeypatch.setattr(default_runner, "source_fingerprint", lambda: "same")
        monkeypatch.setattr(default_runner.subprocess, "run", run)
        assert default_runner.run(plan, fast_dir) != 0
        assert not (tmp_path / ".stage465-default-gate.json").exists()

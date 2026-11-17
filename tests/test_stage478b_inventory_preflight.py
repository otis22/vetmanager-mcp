"""Stage 478B-1: inventory drift fails before expensive suites and review."""

import json
from pathlib import Path
import sys

import pytest
import yaml

from scripts import offline_gate_manifest as gate

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("contour", ["default", "postgres"])
@pytest.mark.parametrize("mutation", ["added", "renamed", "removed"])
def test_preflight_rejects_new_renamed_and_removed_nodes(monkeypatch, tmp_path, contour, mutation):
    original = ["tests/test_sample.py::test_one", "tests/test_sample.py::test_two"]
    (tmp_path / "scripts").mkdir()
    path = tmp_path / "scripts" / f"{contour}_node_inventory.json"
    path.write_text(json.dumps(gate.inventory(original)))
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "collected_nodes", lambda _: original)
    assert gate.check_inventory(contour) == original
    changed = {"added": [*original, "tests/test_new.py::test_three"],
               "renamed": [original[0], "tests/test_sample.py::test_renamed"],
               "removed": original[:1]}[mutation]
    monkeypatch.setattr(gate, "collected_nodes", lambda _: changed)
    with pytest.raises(ValueError, match="inventory"):
        gate.check_inventory(contour)
    assert json.loads(path.read_text()) == gate.inventory(original)  # read-only


@pytest.mark.parametrize("content", [None, "broken", "{}", "[]"])
def test_preflight_cli_fails_closed_on_missing_or_invalid_inventory(monkeypatch, tmp_path, content):
    (tmp_path / "scripts").mkdir()
    if content is not None:
        (tmp_path / "scripts/default_node_inventory.json").write_text(content)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "collected_nodes", lambda _: ["tests/test_a.py::test_one"])
    monkeypatch.setattr(sys, "argv", ["offline_gate_manifest.py", "default", "--check-inventory"])
    assert gate.main() == 1


def test_default_runner_rejects_drift_before_running_any_suite(monkeypatch):
    from scripts import run_default_test_suite as runner

    calls = []

    def reject(contour):
        calls.append(contour)
        raise ValueError("collected nodes differ from versioned inventory")

    monkeypatch.setattr(runner, "check_inventory", reject)
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: pytest.fail("suite started before preflight"))
    assert runner.main() == 1
    assert calls == ["default"]


def test_ci_preflight_blocks_default_postgres_and_validated_tree():
    jobs = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())["jobs"]
    job = jobs["inventory-preflight"]
    assert job["needs"] == ["scope-and-reuse", "build-image"]
    assert job["if"] == "${{ needs.scope-and-reuse.outputs.run_product == 'true' }}"
    assert not job.get("continue-on-error")
    steps = job["steps"]
    assert "actions/download-artifact@v4" in str(steps)
    command = "\n".join(step.get("run", "") for step in steps)
    assert command.index("docker load") < command.index("--check-inventory")
    for contour in ("default", "postgres"):
        assert f"offline_gate_manifest.py {contour} --check-inventory" in command
    for name in ("default", "postgres-activation-telemetry", "validated-tree"):
        assert "inventory-preflight" in jobs[name]["needs"]
        assert "always()" not in jobs[name].get("if", "")


@pytest.mark.parametrize("path", ["tests/test_new.py", "scripts/default_node_inventory.json",
                                  "scripts/postgres_node_inventory.json"])
def test_ci_scope_does_not_skip_test_or_inventory_changes(path):
    from scripts.ci_scope import docs_only, should_run_product

    docs = docs_only(b"M\0" + path.encode() + b"\0")
    assert not docs
    for event in ("pull_request", "push"):
        assert should_run_product(event, docs, True, False)

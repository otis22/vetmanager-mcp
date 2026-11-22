"""Stage 465 fail-closed checks for default and PostgreSQL manifests."""

import pytest
import json
from xml.etree import ElementTree as ET

from scripts import offline_gate_manifest as gate
from scripts.offline_gate_manifest import validate_record


@pytest.mark.parametrize("bad", [
    {"nodes": ["a"], "fingerprint": "current", "complete": True},
    {"nodes": ["a", "a", "b"], "fingerprint": "current", "complete": True},
    {"nodes": ["a", "b"], "fingerprint": "old", "complete": True},
    {"nodes": ["a", "b"], "fingerprint": "current", "complete": False},
])
def test_manifest_rejects_loss_duplicate_stale_or_incomplete(bad) -> None:
    with pytest.raises(ValueError):
        validate_record(bad, expected_nodes=["a", "b"], current_fingerprint="current")


def test_manifest_accepts_exact_complete_current_result() -> None:
    validate_record(
        {"nodes": ["a", "b"], "fingerprint": "current", "complete": True},
        expected_nodes=["a", "b"], current_fingerprint="current",
    )


def test_file_inventory_detects_lost_and_duplicate_nodes() -> None:
    original = ["tests/a.py::one", "tests/a.py::two"]
    baseline = gate.inventory(original)
    assert gate.inventory(original[:1]) != baseline
    assert gate.inventory([*original, original[0]]) != baseline


def test_junit_rejects_skip_and_duplicate(tmp_path) -> None:
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    case = ET.SubElement(suite, "testcase", classname="tests.a", name="one")
    path = tmp_path / "junit.xml"
    ET.ElementTree(root).write(path)
    assert gate.junit_nodes(path, {"tests/a.py"}) == ["tests/a.py::one"]
    ET.SubElement(case, "skipped")
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="skip"):
        gate.junit_nodes(path, {"tests/a.py"})
    case.remove(case.find("skipped"))
    ET.SubElement(suite, "testcase", classname="tests.a", name="one")
    ET.ElementTree(root).write(path)
    with pytest.raises(ValueError, match="duplicate"):
        gate.junit_nodes(path, {"tests/a.py"})


def test_gate_rejects_stale_inventory_and_incomplete_junit(monkeypatch, tmp_path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    expected = ["tests/a.py::one", "tests/a.py::two"]
    (scripts / "default_node_inventory.json").write_text(json.dumps(gate.inventory(expected)))
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    ET.SubElement(suite, "testcase", classname="tests.a", name="one")
    junit = tmp_path / "junit.xml"
    ET.ElementTree(root).write(junit)
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    monkeypatch.setattr(gate, "collected_nodes", lambda contour: expected)
    monkeypatch.setattr(gate, "source_fingerprint", lambda **_kwargs: "current")
    with pytest.raises(ValueError, match="cover"):
        gate.check_gate("default", junit, tmp_path / "out.json", "current")
    ET.SubElement(suite, "testcase", classname="tests.a", name="two")
    ET.ElementTree(root).write(junit)
    record_path = tmp_path / "out.json"
    gate.check_gate("default", junit, record_path, "current")
    gate.verify_record("default", record_path)
    with pytest.raises(ValueError, match="mixed runtime"):
        gate.check_gate("default", junit, tmp_path / "mixed.json", "old")
    monkeypatch.setattr(gate, "source_fingerprint", lambda **_kwargs: "changed")
    with pytest.raises(ValueError, match="stale"):
        gate.verify_record("default", record_path)
    (scripts / "default_node_inventory.json").write_text(json.dumps(gate.inventory(expected[:1])))
    with pytest.raises(ValueError, match="inventory"):
        gate.check_gate("default", junit, tmp_path / "out.json", "changed")


def test_fingerprint_includes_shell_and_coverage_inputs(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(gate.metadata, "distributions", lambda: [])
    for name in (
        "Dockerfile", "docker-compose.yml", "docker-compose.test.yml",
        "pyproject.toml", "pytest.ini", ".coveragerc",
        "uv.lock", "requirements/production.txt", "requirements/test.txt",
        "requirements/audit.txt", "requirements/production-installed.txt",
        "requirements/test-installed.txt",
        "alembic.ini", "tests/fixtures/stage385_resource_gate_sample.json",
        "ops/prometheus/prometheus.yml", "ops/grafana/dashboards/vetmanager-overview.json",
        "ops/grafana/provisioning/dashboards/dashboards.yml",
        "ops/grafana/provisioning/datasources/prometheus.yml",
        ".github/workflows/test.yml", "scripts/default_node_inventory.json",
        "scripts/postgres_node_inventory.json", "scripts/offline_integration_files.json",
        "scripts/test_impact_map.json",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original")
    script = tmp_path / "scripts" / "oracle.sh"
    script.write_text("original")
    for name in ("tests/test_default.py", "tests/test_postgres.py", "tests/test_real.py",
                 "tests/conftest.py", "tests/real_suite_outcomes.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n")
    (tmp_path / "scripts/default_node_inventory.json").write_text(
        json.dumps({"tests/test_default.py": {}}))
    (tmp_path / "scripts/postgres_node_inventory.json").write_text(
        json.dumps({"tests/test_postgres.py": {}}))
    (tmp_path / "scripts/real_group_manifest.json").write_text(
        json.dumps({"groups": {"read": ["tests/test_real.py::test_live"]}}))
    baseline = gate.source_fingerprint(tmp_path)
    script.write_text("changed")
    assert gate.source_fingerprint(tmp_path) != baseline
    script.write_text("original")
    (tmp_path / ".coveragerc").write_text("changed")
    assert gate.source_fingerprint(tmp_path) != baseline
    (tmp_path / ".coveragerc").write_text("original")
    for name in ("alembic.ini", "tests/fixtures/stage385_resource_gate_sample.json"):
        path = tmp_path / name
        path.write_text("changed")
        assert gate.source_fingerprint(tmp_path) != baseline, name
        path.write_text("original")
    path = tmp_path / "ops/prometheus/prometheus.yml"
    path.write_text("changed")
    assert gate.source_fingerprint(tmp_path) != baseline

"""Stage 469: contour input drift must invalidate only affected evidence."""

import json
import hashlib

import pytest

from scripts import offline_gate_manifest as gate
from scripts.real_group_gate import validate_shard


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(gate.metadata, "distributions", lambda: [])
    fixed = (
        "Dockerfile", "docker-compose.yml", "docker-compose.test.yml",
        "pyproject.toml", "pytest.ini", ".coveragerc", "alembic.ini",
        "tests/fixtures/stage385_resource_gate_sample.json",
        ".github/workflows/test.yml", "scripts/offline_integration_files.json",
        "scripts/test_impact_map.json",
        "tests/conftest.py", "tests/real_suite_outcomes.py",
        "scripts/run_opt_in_real_test_suite.py", "app.py",
        "tests/test_default.py", "tests/test_postgres.py", "tests/test_real.py",
    )
    for name in fixed:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n" if path.suffix == ".py" else "original", encoding="utf-8")
    (tmp_path / "scripts/default_node_inventory.json").write_text(json.dumps({"tests/test_default.py": {}}))
    (tmp_path / "scripts/postgres_node_inventory.json").write_text(json.dumps({"tests/test_postgres.py": {}}))
    (tmp_path / "scripts/real_group_manifest.json").write_text(json.dumps({
        "groups": {"read": ["tests/test_real.py::test_live"]}, "shared_helpers": ["tests/conftest.py"]}))
    return tmp_path


def fingerprints(root):
    return {name: gate.source_fingerprint(root, contour=name)
            for name in ("default", "postgres", "real")}


@pytest.mark.parametrize(("path", "changed"), [
    ("tests/test_real.py", {"real"}),
    ("tests/test_default.py", {"default"}),
    ("tests/test_postgres.py", {"postgres"}),
    ("tests/conftest.py", {"default", "postgres", "real"}),
    ("app.py", {"default", "postgres", "real"}),
    ("docker-compose.test.yml", {"default", "postgres", "real"}),
    ("scripts/run_opt_in_real_test_suite.py", {"default", "postgres", "real"}),
    ("pyproject.toml", {"default", "postgres", "real"}),
    ("docker-compose.override.yml", {"default", "postgres", "real"}),
    (".env", {"default", "postgres", "real"}),
    ("scripts/real_group_manifest.json", {"real"}),
    ("scripts/default_node_inventory.json", {"default"}),
    ("scripts/test_impact_map.json", {"default", "postgres", "real"}),
    ("docs/process.md", set()),
])
def test_input_change_invalidates_exact_contours(source_tree, path, changed):
    before = fingerprints(source_tree)
    target = source_tree / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((target.read_text() + "\n") if target.suffix == ".json" else "changed", encoding="utf-8")
    after = fingerprints(source_tree)
    assert {name for name in before if before[name] != after[name]} == changed


def test_unknown_test_file_invalidates_every_contour(source_tree):
    before = fingerprints(source_tree)
    (source_tree / "tests/test_unclassified.py").write_text("new")
    assert all(before[name] != after for name, after in fingerprints(source_tree).items())


def test_missing_required_inventory_fails_closed(source_tree):
    (source_tree / "scripts/postgres_node_inventory.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        gate.source_fingerprint(source_tree, contour="postgres")


@pytest.mark.parametrize("statement", [
    "from tests.test_default import helper\n",
    "from tests import test_default\n",
    "from . import test_default\n",
])
def test_imported_test_helper_is_in_importer_contour(source_tree, statement):
    importer = source_tree / "tests/test_real.py"
    importer.write_text(statement)
    before = fingerprints(source_tree)
    (source_tree / "tests/test_default.py").write_text("changed")
    after = fingerprints(source_tree)
    assert after["real"] != before["real"]
    assert after["postgres"] == before["postgres"]


@pytest.mark.parametrize("helper", ["tests/conftest.py", "scripts/run_opt_in_real_test_suite.py"])
def test_shared_helper_import_propagates_all_contours(source_tree, helper):
    (source_tree / helper).write_text("from tests import test_default\n")
    before = fingerprints(source_tree)
    (source_tree / "tests/test_default.py").write_text("changed")
    after = fingerprints(source_tree)
    assert all(after[name] != before[name] for name in before)
    assert source_tree / "tests/test_default.py" in gate.contour_input_paths(
        source_tree, "real", shared_only=True)


def test_shard_rejects_stale_current_image_id(tmp_path):
    node = "tests/test_real.py::test_live"
    manifest = {"groups": {"read": [node]}}
    shard = {"group": "read", "nodes": [node], "image_id": "old",
             "manifest_hash": "m", "runtime_fingerprint": "r", "test_fingerprint": "t",
             "contour_identity": "c", "dependency_fingerprint": "d"}
    expected = {"manifest_hash": "m", "runtime_fingerprint": "r",
                "test_fingerprint": "t", "contour_identity": "c",
                "dependency_fingerprint": "d", "image_id": "current"}
    with pytest.raises(ValueError, match="image_id"):
        validate_shard(manifest, shard, tmp_path, expected)


def test_current_real_dependency_comes_from_image(monkeypatch):
    from scripts.run_isolated_test_suite import current_real_image_evidence

    calls = []
    def fake_output(command, **kwargs):
        calls.append(command)
        if command[-3:] == ["config", "--format", "json"]:
            return json.dumps({"services": {"test": {"image": "test-image"}}})
        if command[:3] == ["docker", "image", "inspect"]:
            return "sha256:current\n"
        if command[:3] == ["docker", "run", "--rm"]:
            return "package==new\n"
        raise AssertionError(command)
    monkeypatch.setattr("subprocess.check_output", fake_output)
    evidence = current_real_image_evidence(["docker", "compose"], {})
    assert evidence["image_id"] == "sha256:current"
    assert evidence["dependency_fingerprint"] == hashlib.sha256(b"package==new\n").hexdigest()
    assert ["docker", "run", "--rm", "--entrypoint", "python", "sha256:current",
            "-m", "pip", "freeze"] in calls


def test_real_group_builds_only_first_image_for_evidence_root(tmp_path):
    from scripts.run_isolated_test_suite import group_image_build_required, pin_group_image

    assert group_image_build_required(tmp_path, requested=False) is True
    pin_group_image(tmp_path, "sha256:first")
    assert group_image_build_required(tmp_path, requested=False) is False
    with pytest.raises(ValueError, match="rebuild"):
        group_image_build_required(tmp_path, requested=True)


def test_real_group_rejects_image_change_between_shards(tmp_path):
    from scripts.run_isolated_test_suite import pin_group_image

    pin_group_image(tmp_path, "sha256:first")
    with pytest.raises(ValueError, match="image changed"):
        pin_group_image(tmp_path, "sha256:second")

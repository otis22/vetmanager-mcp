"""Fail closed on stale, incomplete default and PostgreSQL test evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
MARKERS = {
    "default": "not real_api and not real_browser and not postgres",
    "postgres": "postgres",
}

CONTOURS = frozenset(("default", "postgres", "real"))
SHARED_TEST_HELPERS = ("tests/conftest.py", "tests/real_suite_outcomes.py")
COMMON_CONFIG = (
    "Dockerfile", "docker-compose.yml", "docker-compose.test.yml",
    "pyproject.toml", "pytest.ini", ".coveragerc", "alembic.ini",
    "uv.lock", "requirements/production.txt", "requirements/test.txt",
    "requirements/audit.txt", "requirements/production-installed.txt",
    "requirements/test-installed.txt",
    "tests/fixtures/stage385_resource_gate_sample.json", ".github/workflows/test.yml",
    "scripts/test_impact_map.json",
)
CONTOUR_CONFIG = {
    "default": ("scripts/default_node_inventory.json", "scripts/offline_integration_files.json"),
    "postgres": ("scripts/postgres_node_inventory.json",),
    "real": ("scripts/real_group_manifest.json",),
}


def _inventory_paths(root: Path) -> dict[str, set[Path]]:
    """Read the three versioned inventories; an unknown path stays conservative."""
    result = {}
    for contour in CONTOURS:
        name = CONTOUR_CONFIG[contour][0]
        try:
            data = json.loads((root / name).read_text(encoding="utf-8"))
            names = (data.keys() if contour != "real" else
                     (node.split("::", 1)[0] for nodes in data["groups"].values() for node in nodes))
            paths = set()
            for name in names:
                if not isinstance(name, str) or not name.startswith("tests/") or not name.endswith(".py"):
                    raise ValueError("invalid inventory path")
                path = root / name
                if not path.is_file():
                    raise ValueError(f"missing inventory input: {name}")
                paths.add(path)
            if not paths:
                raise ValueError("empty contour inventory")
            result[contour] = paths
        except (OSError, json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"missing or invalid contour inventory: {contour}") from exc
    return result


def test_imports(root: Path, path: Path) -> set[Path]:
    """Resolve static imports between test modules, including relative imports."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"invalid test input: {path.relative_to(root)}") from exc
    dependencies = set()
    for statement in ast.walk(tree):
        if isinstance(statement, ast.Import):
            modules = [alias.name for alias in statement.names]
        elif isinstance(statement, ast.ImportFrom):
            prefix = ".".join(path.relative_to(root).with_suffix("").parts[:-statement.level]) if statement.level else ""
            base = ".".join(filter(None, (prefix, statement.module))) if statement.level else statement.module
            modules = [base, *(f"{base}.{alias.name}" for alias in statement.names
                               if base and alias.name != "*")]
        else:
            continue
        for module in modules:
            if module and module.startswith("tests."):
                dependency = root / (module.replace(".", "/") + ".py")
                if dependency.is_file():
                    dependencies.add(dependency)
    return dependencies


def contour_input_paths(root: Path, contour: str, *, shared_only: bool = False) -> list[Path]:
    """Select source inputs without trusting an incomplete test-file inventory."""
    if contour not in CONTOURS:
        raise ValueError("unknown contour")
    inventories = _inventory_paths(root)
    all_python = {p for p in root.rglob("*.py") if not any(
        part in {".git", ".venv", "__pycache__"} for part in p.relative_to(root).parts)}
    tests = {p for p in all_python if p.relative_to(root).parts[0] == "tests" and p.name.startswith("test_")}
    listed = set().union(*inventories.values())
    unknown = tests - listed
    owners = {p: ({name for name, paths in inventories.items() if p in paths}
                  if p in tests else set(CONTOURS)) for p in all_python}
    for path in unknown:
        owners[path] = set(CONTOURS)
    imports = {p: test_imports(root, p) for p in all_python}
    changed = True
    while changed:
        changed = False
        for importer, dependencies in imports.items():
            for dependency in dependencies & all_python:
                before = len(owners[dependency])
                owners[dependency].update(owners[importer])
                changed |= len(owners[dependency]) != before
    common = all_python - tests
    common.update(unknown)
    common.update(p for p in tests if owners[p] == set(CONTOURS))
    common.update(root / name for name in SHARED_TEST_HELPERS)
    common.update(root / name for name in COMMON_CONFIG)
    common.update(p for p in (root / "scripts").rglob("*.sh"))
    common.update(p for p in (root / "ops").rglob("*") if p.is_file())
    common.update(p for p in (root / ".github/workflows").glob("*.y*ml") if p.is_file())
    common.update(p for p in (root / ".env", root / "docker-compose.override.yml") if p.is_file())
    if not shared_only:
        common.update(p for p in tests if contour in owners[p])
        common.update(root / name for name in CONTOUR_CONFIG[contour])
    paths = sorted(common)
    for path in paths:
        if not path.is_file():
            raise ValueError(f"missing fingerprint input: {path.relative_to(root)}")
    return paths


def validate_record(record: dict, *, expected_nodes: list[str], current_fingerprint: str) -> None:
    """Reject missing, duplicated, mixed-runtime or incomplete gate evidence."""
    nodes = record.get("nodes")
    if not isinstance(nodes, list) or any(not isinstance(node, str) for node in nodes):
        raise ValueError("invalid manifest nodes")
    if len(nodes) != len(set(nodes)) or sorted(nodes) != sorted(expected_nodes):
        raise ValueError("lost, duplicate or substituted node")
    if record.get("fingerprint") != current_fingerprint:
        raise ValueError("stale or mixed runtime fingerprint")
    if record.get("complete") is not True:
        raise ValueError("incomplete gate result")


def source_fingerprint(root: Path = ROOT, *, contour: str = "default") -> str:
    """Hash the selected contour's sources, config and installed versions."""
    digest = hashlib.sha256()
    for path in contour_input_paths(root, contour):
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(path.read_bytes())
    versions = sorted((dist.metadata.get("Name", ""), dist.version) for dist in metadata.distributions())
    digest.update(json.dumps(versions, separators=(",", ":")).encode())
    return digest.hexdigest()


def collected_nodes(contour: str) -> list[str]:
    """Collect one contour without executing its tests."""
    if contour not in MARKERS:
        raise ValueError("unknown offline contour")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q", "-m", MARKERS[contour]],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ValueError(f"{contour} collection failed with exit {result.returncode}")
    nodes = [line for line in result.stdout.splitlines() if line.startswith("tests/") and "::" in line]
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("empty or duplicate collection")
    return nodes


def inventory(nodes: list[str]) -> dict[str, dict[str, str | int]]:
    """Record independent per-file counts and exact node-set hashes."""
    grouped: dict[str, list[str]] = {}
    for node in nodes:
        grouped.setdefault(node.split("::", 1)[0], []).append(node)
    return {
        name: {"count": len(items), "sha256": hashlib.sha256(
            "\n".join(sorted(items)).encode()
        ).hexdigest()}
        for name, items in sorted(grouped.items())
    }


def check_inventory(contour: str) -> list[str]:
    """Reject collection drift before executing a suite; never rewrite inventory."""
    if contour not in MARKERS:
        raise ValueError("unknown offline contour")
    path = ROOT / "scripts" / f"{contour}_node_inventory.json"
    try:
        expected = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("missing or invalid expected inventory") from exc
    nodes = collected_nodes(contour)
    if inventory(nodes) != expected:
        raise ValueError("collected nodes differ from versioned inventory")
    print(f"Inventory preflight {contour}: {len(nodes)} nodes match", file=sys.stderr)
    return nodes


def junit_nodes(path: Path, expected_files: set[str]) -> list[str]:
    """Decode pytest JUnit including class methods and reject non-passes."""
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("missing or invalid JUnit") from exc
    nodes = []
    for case in root.iter("testcase"):
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            raise ValueError("JUnit has skip, failure or error")
        parts = case.attrib.get("classname", "").split(".")
        paths = [(i, "/".join(parts[:i]) + ".py") for i in range(2, len(parts) + 1)]
        matches = [(i, p) for i, p in paths if p in expected_files]
        if not matches:
            raise ValueError("JUnit has unknown file")
        i, file = max(matches)
        nodes.append("::".join((file, *parts[i:], case.attrib.get("name", ""))))
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("empty or duplicate JUnit")
    return nodes


def check_gate(contour: str, junit: Path, output: Path, starting_fingerprint: str) -> dict:
    """Verify current collection, committed inventory and JUnit before recording."""
    expected_path = ROOT / "scripts" / f"{contour}_node_inventory.json"
    try:
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("missing or invalid expected inventory") from exc
    nodes = collected_nodes(contour)
    if inventory(nodes) != expected:
        raise ValueError("collected nodes differ from versioned inventory")
    actual = junit_nodes(junit, set(expected))
    if sorted(actual) != sorted(nodes):
        raise ValueError("JUnit does not cover collected nodes")
    fingerprint = source_fingerprint(contour=contour)
    if starting_fingerprint != fingerprint:
        raise ValueError("mixed runtime during gate")
    record = {"schema_version": 1, "contour": contour, "nodes": nodes,
              "fingerprint": fingerprint, "complete": True}
    validate_record(record, expected_nodes=nodes, current_fingerprint=fingerprint)
    output.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
    return record


def verify_record(contour: str, path: Path) -> None:
    """Reject an earlier manifest after any relevant source or inventory drift."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        expected = json.loads((ROOT / "scripts" / f"{contour}_node_inventory.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("missing or invalid gate manifest/inventory") from exc
    if record.get("schema_version") != 1 or record.get("contour") != contour:
        raise ValueError("wrong gate manifest schema or contour")
    nodes = collected_nodes(contour)
    if inventory(nodes) != expected:
        raise ValueError("stale node inventory")
    validate_record(record, expected_nodes=nodes, current_fingerprint=source_fingerprint(contour=contour))


def main() -> int:
    """Generate reviewed inventory or validate a completed offline gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contour", choices=tuple(MARKERS))
    parser.add_argument("--generate-inventory", action="store_true")
    parser.add_argument("--check-inventory", action="store_true")
    parser.add_argument("--output-nodes", type=Path)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-manifest", type=Path)
    parser.add_argument("--write-fingerprint", type=Path)
    parser.add_argument("--starting-fingerprint-file", type=Path)
    args = parser.parse_args()
    try:
        if args.check_inventory:
            nodes = check_inventory(args.contour)
            if args.output_nodes:
                args.output_nodes.write_text(json.dumps(nodes) + "\n", encoding="utf-8")
        elif args.write_fingerprint:
            args.write_fingerprint.write_text(source_fingerprint(contour=args.contour) + "\n", encoding="utf-8")
        elif args.verify_manifest:
            verify_record(args.contour, args.verify_manifest)
        elif args.generate_inventory:
            target = ROOT / "scripts" / f"{args.contour}_node_inventory.json"
            target.write_text(json.dumps(inventory(collected_nodes(args.contour)), indent=2, sort_keys=True) + "\n")
        elif args.junit and args.output:
            if not args.starting_fingerprint_file:
                raise ValueError("missing start fingerprint")
            check_gate(args.contour, args.junit, args.output,
                       args.starting_fingerprint_file.read_text(encoding="utf-8").strip())
        else:
            parser.error("provide --generate-inventory or both --junit and --output")
    except ValueError as exc:
        print(f"Offline gate rejected: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

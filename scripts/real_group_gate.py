"""Exact-node validation and fingerprints for the stage 466 real shards."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
import xml.etree.ElementTree as ET

from scripts.offline_gate_manifest import contour_input_paths, test_imports

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts/real_group_manifest.json"


def digest_files(paths):
    digest = hashlib.sha256()
    for path in sorted(set(Path(p) for p in paths)):
        if not path.is_file():
            raise ValueError(f"missing fingerprint input: {path}")
        digest.update(str(path.relative_to(ROOT)).encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def runtime_files():
    return contour_input_paths(ROOT, "real", shared_only=True)


def test_files(manifest, group):
    nodes = manifest["groups"][group]
    files = {ROOT / node.split("::")[0] for node in nodes} | {ROOT / p for p in manifest["shared_helpers"]}
    pending = list(files)
    while pending:
        path = pending.pop()
        if path.suffix != ".py" or not path.is_file():
            continue
        for dependency in test_imports(ROOT, path):
            if dependency not in files:
                files.add(dependency)
                pending.append(dependency)
    return sorted(files)


def manifest_hash(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_manifest(manifest, collected):
    if manifest.get("schema_version") != 1 or manifest.get("marker_expression") != "real_api or real_browser":
        raise ValueError("unknown manifest schema or marker")
    groups = manifest.get("groups")
    if not isinstance(groups, dict) or not groups:
        raise ValueError("empty groups")
    nodes = [n for group in groups.values() for n in group]
    if not nodes or len(nodes) != len(set(nodes)) or set(nodes) != set(collected) or len(nodes) != len(collected):
        raise ValueError("manifest does not cover exact collected nodes")
    if not set(manifest.get("required_nodes", [])) <= set(nodes):
        raise ValueError("required node missing")
    if not all(isinstance(n, str) and n.startswith("tests/") and "::" in n for n in nodes):
        raise ValueError("invalid node ID")
    return nodes


def junit_nodes(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise ValueError("missing or invalid JUnit") from exc
    cases = list(root.iter("testcase"))
    if not cases or any(case.find(tag) is not None for case in cases for tag in ("skipped", "failure", "error")):
        raise ValueError("JUnit skip or failure")
    nodes = [case.get("classname", "").replace(".", "/") + ".py::" + case.get("name", "") for case in cases]
    if len(nodes) != len(set(nodes)):
        raise ValueError("duplicate JUnit node")
    return nodes


def validate_shard(manifest, shard, directory, expected):
    group = shard.get("group")
    if group not in manifest["groups"]:
        raise ValueError("unknown group")
    for key, value in expected.items():
        if shard.get(key) != value:
            raise ValueError(f"stale {key}")
    if shard.get("nodes") != manifest["groups"][group] or not shard.get("image_id"):
        raise ValueError("missing, duplicate or substituted node/image")
    if not isinstance(shard.get("results"), dict) or any(shard["results"].get(k) != 0 for k in ("test", "cleanup")):
        raise ValueError("test or cleanup failed")
    created = shard.get("created_at")
    if type(created) not in (int, float) or not 0 <= time.time() - created <= 86400:
        raise ValueError("stale or future shard")
    try:
        summary = json.loads((Path(directory) / "summary.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("missing or invalid cleanup evidence") from exc
    if summary.get("results", {}).get("cleanup") != 0 or not (Path(directory) / "cleanup.log").is_file():
        raise ValueError("cleanup evidence missing or failed")
    nodes = junit_nodes(Path(directory) / f"{group}.xml")
    try:
        outcome = json.loads((Path(directory) / f"{group}.outcome.json").read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("missing or invalid outcome") from exc
    counts = outcome.get("counts", {})
    wanted = set(shard["nodes"])
    if set(nodes) != wanted or len(nodes) != len(wanted) or outcome.get("collected") != len(wanted):
        raise ValueError("JUnit/manifest node mismatch")
    if counts.get("passed") != len(wanted) or any(counts.get(k) != 0 for k in ("failed", "skipped-not-configured", "skipped-error")):
        raise ValueError("outcome skip or failure")
    if outcome.get("nodes") != {node: "passed" for node in wanted}:
        raise ValueError("outcome node mismatch")
    return True


def validate_aggregate(manifest, attempts, directory, expected_by_group):
    if set(attempts) != set(manifest["groups"]):
        raise ValueError("incomplete aggregate")
    for group, history in attempts.items():
        if not history:
            raise ValueError("missing attempt")
        validate_shard(manifest, history[-1], history[-1].get("evidence_dir", directory), expected_by_group[group])
    return True


def load_latest_attempts(root):
    """Keep the append-only index, but load evidence only for each latest attempt."""
    root = Path(root)
    latest = {}
    try:
        lines = (root / "attempts.jsonl").read_text().splitlines()
        for line in lines:
            entry = json.loads(line)
            if (not isinstance(entry, dict) or set(entry) != {"group", "directory"}
                    or not isinstance(entry["group"], str)
                    or not isinstance(entry["directory"], str)
                    or Path(entry["directory"]).name != entry["directory"]):
                raise ValueError("invalid attempt index entry")
            latest[entry["group"]] = entry["directory"]
        if not latest:
            raise ValueError("empty attempt index")
        attempts = {}
        for group, directory in latest.items():
            path = root / directory
            shard = json.loads((path / "shard.json").read_text())
            if not isinstance(shard, dict) or shard.get("group") != group:
                raise ValueError("latest shard does not match index")
            shard["evidence_dir"] = str(path)
            attempts[group] = [shard]
        return attempts
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError("missing or invalid latest attempt evidence") from exc

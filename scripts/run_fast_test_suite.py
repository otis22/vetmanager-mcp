#!/usr/bin/env python3
"""Run the fast inner-loop contour with blocking warnings as errors."""

from __future__ import annotations

import os
import argparse
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from test_contours import FAST_TEST_CONTOUR
from warning_policy import build_warning_error_flags
from scripts.offline_gate_manifest import check_inventory, junit_nodes, source_fingerprint
from scripts.split_default_gate import ci_fast_shards, collected_fast_nodes


SHARD_COUNT = 12


def run_ci_shard(directory: Path, index: int) -> int:
    if not 0 <= index < SHARD_COUNT:
        raise ValueError("invalid fast shard index")
    check_inventory("default")
    fingerprint = source_fingerprint()
    nodes = collected_fast_nodes()
    shards = ci_fast_shards(nodes)
    if len(shards) != SHARD_COUNT:
        raise ValueError("fast shard count mismatch")
    shard = shards[index]
    if not shard:
        raise ValueError("empty fast shard")
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.iterdir():
        if stale.is_file():
            stale.unlink()
    junit = directory / f"shard-{index}.xml"
    coverage = directory / f".coverage.shard-{index}"
    command = [sys.executable, *[item for flag in build_warning_error_flags()
                                for item in ("-W", flag)], "-m", "pytest", "-q",
               "-m", FAST_TEST_CONTOUR.marker_expression, "--cov", "--cov-config=.coveragerc",
               "--cov-report=", "--junitxml=" + str(junit), *shard]
    env = dict(os.environ)
    env["COVERAGE_FILE"] = str(coverage)
    result = subprocess.run(command, env=env, check=False)
    if result.returncode:
        return result.returncode
    if not coverage.is_file():
        raise ValueError("shard coverage missing")
    actual = junit_nodes(junit, {node.split("::", 1)[0] for node in shard})
    if sorted(actual) != sorted(shard) or source_fingerprint() != fingerprint:
        raise ValueError("shard JUnit or fingerprint changed")
    (directory / f"fingerprint-{index}.txt").write_text(fingerprint + "\n")
    print(f"Fast shard {index}: {len(shard)} nodes match")
    return 0


def aggregate_ci_shards(parts: Path, directory: Path) -> int:
    check_inventory("default")
    fingerprint = source_fingerprint()
    nodes = collected_fast_nodes()
    shards = ci_fast_shards(nodes)
    if len(shards) != SHARD_COUNT:
        raise ValueError("fast shard count mismatch")
    expected_parts = {f"ci-fast-shard-{index}" for index in range(SHARD_COUNT)}
    actual_parts = {part.name for part in parts.iterdir()}
    if actual_parts != expected_parts:
        raise ValueError("missing or unexpected fast shard part")
    all_cases = ET.Element("testsuites")
    coverage_paths = []
    for index, shard in enumerate(shards):
        part = parts / f"ci-fast-shard-{index}"
        junit = part / f"shard-{index}.xml"
        coverage = part / f".coverage.shard-{index}"
        if (part / f"fingerprint-{index}.txt").read_text().strip() != fingerprint:
            raise ValueError("shard fingerprint mismatch")
        if not coverage.is_file():
            raise ValueError("shard coverage missing")
        actual = junit_nodes(junit, {node.split("::", 1)[0] for node in shard})
        if sorted(actual) != sorted(shard):
            raise ValueError("shard JUnit differs from selected nodes")
        coverage_paths.append(str(coverage))
        for suite in ET.parse(junit).getroot().iter("testsuite"):
            all_cases.append(suite)
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.iterdir():
        if stale.is_file():
            stale.unlink()
    ET.ElementTree(all_cases).write(directory / "fast.xml")
    if sorted(junit_nodes(directory / "fast.xml", {n.split("::", 1)[0] for n in nodes})) != sorted(nodes):
        raise ValueError("combined fast JUnit differs from collection")
    combined = directory / ".coverage.fast"
    merge = subprocess.run([sys.executable, "-W", "error", "-m", "coverage", "combine", "--keep",
                            "--data-file=" + str(combined), *coverage_paths], check=False)
    if merge.returncode or not combined.is_file() or source_fingerprint() != fingerprint:
        raise ValueError("fast coverage or fingerprint mismatch")
    (directory / "fingerprint.txt").write_text(fingerprint + "\n")
    print(f"Fast aggregate: {len(nodes)} distinct nodes across {SHARD_COUNT} shards")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ci-evidence", type=Path)
    parser.add_argument("--ci-shard-index", type=int)
    parser.add_argument("--ci-aggregate-parts", type=Path)
    args = parser.parse_args()
    if args.ci_evidence:
        try:
            if args.ci_shard_index is not None and args.ci_aggregate_parts is None:
                return run_ci_shard(args.ci_evidence, args.ci_shard_index)
            if args.ci_aggregate_parts is not None and args.ci_shard_index is None:
                return aggregate_ci_shards(args.ci_aggregate_parts, args.ci_evidence)
            raise ValueError("choose shard or aggregate mode")
        except (OSError, ValueError, ET.ParseError) as exc:
            print(f"Fast evidence rejected: {exc}", file=sys.stderr)
            return 1
    command = [
        sys.executable,
        *[item for flag in build_warning_error_flags() for item in ("-W", flag)],
        "-m",
        "pytest",
        "tests/",
        "-v",
        "-m",
        FAST_TEST_CONTOUR.marker_expression,
    ]
    env = dict(os.environ)
    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

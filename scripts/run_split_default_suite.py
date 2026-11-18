#!/usr/bin/env python3
"""Run only selected non-fast nodes and validate the CI aggregate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.offline_gate_manifest import check_inventory, source_fingerprint, validate_record
from scripts.split_default_gate import collected_fast_nodes, partition, validate_union
from test_contours import DEFAULT_TEST_CONTOUR
from warning_policy import build_warning_error_flags


def run(plan_path: Path, fast_dir: Path) -> int:
    full = check_inventory("default")
    gate = subprocess.run([sys.executable, str(ROOT / "scripts/check_known_issue_tool_names.py")],
                          check=False)
    if gate.returncode:
        return gate.returncode
    fast = collected_fast_nodes()
    plan = json.loads(plan_path.read_text())
    if set(plan) != {"mode", "owners", "postgres", "reason"} or type(plan["postgres"]) is not bool:
        raise ValueError("invalid plan schema")
    selected_fast, remainder = partition(full, fast, plan)
    fingerprint = source_fingerprint()
    if (fast_dir / "fingerprint.txt").read_text().strip() != fingerprint:
        raise ValueError("fast fingerprint differs from default")
    fast_coverage = fast_dir / ".coverage.fast"
    if not fast_coverage.is_file():
        raise ValueError("fast coverage missing")
    remainder_junit = None
    coverage_paths = [fast_coverage]
    if remainder:
        remainder_junit = ROOT / "ci-default-evidence" / "remainder.xml"
        remainder_junit.parent.mkdir(exist_ok=True)
        coverage_file = remainder_junit.parent / ".coverage.remainder"
        for stale in (remainder_junit, coverage_file):
            stale.unlink(missing_ok=True)
        command = [sys.executable, *[item for flag in build_warning_error_flags()
                                    for item in ("-W", flag)], "-m", "pytest", "-v",
                   "--cov", "--cov-config=.coveragerc", "--cov-report=",
                   "--junitxml=" + str(remainder_junit), "-m",
                   DEFAULT_TEST_CONTOUR.marker_expression, *remainder]
        env = dict(os.environ)
        env["COVERAGE_FILE"] = str(coverage_file)
        result = subprocess.run(command, env=env, check=False)
        if result.returncode:
            return result.returncode
        if not coverage_file.is_file():
            raise ValueError("remainder coverage missing")
        coverage_paths.append(coverage_file)
    validate_union(full, selected_fast, remainder, fast_dir / "fast.xml", remainder_junit)
    if source_fingerprint() != fingerprint:
        raise ValueError("mixed runtime during aggregate")
    selected = sorted(selected_fast + remainder)
    if plan["mode"] == "full":
        validate_record({"nodes": selected, "fingerprint": fingerprint, "complete": True},
                        expected_nodes=full, current_fingerprint=fingerprint)
    else:
        expected_selected = set(fast) | {
            node for node in full if node.split("::", 1)[0] in plan["owners"]}
        if set(selected) != expected_selected:
            raise ValueError("lost or unexpected owning node")
    (ROOT / ".coverage").unlink(missing_ok=True)
    combine = subprocess.run([sys.executable, "-W", "error", "-m", "coverage", "combine", "--keep",
                              *map(str, coverage_paths)], check=False)
    if combine.returncode:
        return combine.returncode
    product_source = "--include=" + str(ROOT / "*")
    for args in (["report", "-m", "--skip-covered", product_source],
                 ["xml", "-o", "coverage.xml", product_source]):
        result = subprocess.run([sys.executable, "-m", "coverage", *args], check=False)
        if result.returncode:
            return result.returncode
    record = {"schema_version": 1, "contour": "default", "nodes": selected,
              "fingerprint": fingerprint, "complete": True} if plan["mode"] == "full" else {
              "schema_version": 2, "contour": "default", "mode": "isolated",
              "nodes": selected, "excluded_nodes": sorted(set(full) - set(selected)),
              "fast_nodes": selected_fast, "remainder_nodes": remainder,
              "fingerprint": fingerprint, "complete": True}
    (ROOT / ".stage465-default-gate.json").write_text(json.dumps(record, sort_keys=True) + "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--fast-evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        return run(args.plan, args.fast_evidence)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"Split default rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

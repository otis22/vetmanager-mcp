"""Prove exact coverage of selected default nodes across CI partitions."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from collections import defaultdict

from scripts.offline_gate_manifest import junit_nodes
from test_contours import FAST_TEST_CONTOUR


def collected_fast_nodes() -> list[str]:
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q",
                             "-m", FAST_TEST_CONTOUR.marker_expression],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"fast collection failed with exit {result.returncode}")
    nodes = [line for line in result.stdout.splitlines() if line.startswith("tests/") and "::" in line]
    if not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("empty or duplicate fast collection")
    return nodes


def shard_fast_nodes(nodes: list[str], count: int) -> list[list[str]]:
    if count < 1 or not nodes or len(nodes) != len(set(nodes)):
        raise ValueError("invalid fast shard input")
    files: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        files[node.split("::", 1)[0]].append(node)
    shards: list[list[str]] = [[] for _ in range(count)]
    loads = [0] * count
    for _, grouped in sorted(files.items(), key=lambda item: (-len(item[1]), item[0])):
        index = min(range(count), key=lambda i: (loads[i], i))
        shards[index].extend(grouped)
        loads[index] += len(grouped)
    if sorted(node for shard in shards for node in shard) != sorted(nodes):
        raise ValueError("fast shard lost node")
    return shards


def ci_fast_shards(nodes: list[str]) -> list[list[str]]:
    """Keep measured order-sensitive scanner tests in clean pytest processes."""
    dedicated = ("tests/test_stage285_runtime_env_reaches_container.py",
                 "tests/test_stage337_user_name_search_hint.py")
    shards = shard_fast_nodes(nodes, 8)
    for file in dedicated:
        own = [node for shard in shards for node in shard if node.split("::", 1)[0] == file]
        for shard in shards:
            shard[:] = [node for node in shard if node.split("::", 1)[0] != file]
        shards.append(own)
    if sorted(node for shard in shards for node in shard) != sorted(nodes):
        raise ValueError("dedicated fast shard lost node")
    return shards


def partition(full: list[str], fast: list[str], plan: dict) -> tuple[list[str], list[str]]:
    if len(full) != len(set(full)) or len(fast) != len(set(fast)) or not set(fast) <= set(full):
        raise ValueError("invalid collection or duplicate node")
    if plan.get("mode") == "full":
        selected = set(full)
    elif plan.get("mode") == "isolated":
        owners = plan.get("owners")
        if not isinstance(owners, list) or not owners or len(owners) != len(set(owners)):
            raise ValueError("invalid owner plan")
        files = {node.split("::", 1)[0] for node in full}
        if any(owner not in files for owner in owners):
            raise ValueError("owner absent from inventory")
        selected = set(fast) | {node for node in full if node.split("::", 1)[0] in owners}
    else:
        raise ValueError("unknown plan mode")
    remainder = sorted(selected - set(fast))
    return sorted(fast), remainder


def validate_union(full: list[str], fast: list[str], remainder: list[str],
                   fast_junit: Path, remainder_junit: Path | None) -> None:
    if len(full) != len(set(full)) or len(fast) != len(set(fast)) or len(remainder) != len(set(remainder)):
        raise ValueError("duplicate expected node")
    if set(fast) & set(remainder) or not set(fast + remainder) <= set(full):
        raise ValueError("overlap or unknown node")
    expected_files = {node.split("::", 1)[0] for node in full}
    actual_fast = junit_nodes(fast_junit, expected_files)
    if sorted(actual_fast) != sorted(fast):
        raise ValueError("fast JUnit differs from plan")
    if remainder:
        if remainder_junit is None:
            raise ValueError("missing remainder JUnit")
        actual_remainder = junit_nodes(remainder_junit, expected_files)
        if sorted(actual_remainder) != sorted(remainder):
            raise ValueError("remainder JUnit differs from plan")
    elif remainder_junit is not None:
        raise ValueError("unexpected remainder JUnit")

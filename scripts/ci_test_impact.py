#!/usr/bin/env python3
"""Conservative, versioned PR test-impact decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = (".github/", "scripts/", "tests/")
DOC_FILES = {"README.md", "Roadmap.md", "Roadmap-archive.md", "AssumptionLog.md"}


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate map key")
        value[key] = item
    return value


def _map(root: Path) -> dict:
    data = json.loads((root / "scripts/test_impact_map.json").read_text(), object_pairs_hook=_pairs)
    if not isinstance(data, dict) or set(data) != {"schema_version", "isolated"} or data["schema_version"] != 1:
        raise ValueError("invalid impact map schema")
    isolated = data["isolated"]
    if not isinstance(isolated, dict) or not isolated:
        raise ValueError("empty impact map")
    inventory = json.loads((root / "scripts/default_node_inventory.json").read_text())
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("invalid default inventory")
    for path, item in isolated.items():
        if (not isinstance(path, str) or not path.startswith("tools/") or not path.endswith(".py")
                or path.startswith(PROTECTED) or not isinstance(item, dict)
                or set(item) != {"owners", "postgres"} or type(item["postgres"]) is not bool
                or not isinstance(item["owners"], list) or not item["owners"]
                or len(item["owners"]) != len(set(item["owners"]))):
            raise ValueError("invalid isolated rule")
        if any(not isinstance(owner, str) or not owner.startswith("tests/test_")
               or not owner.endswith(".py") for owner in item["owners"]):
            raise ValueError("invalid owner")
        if any(owner not in inventory or not isinstance(inventory[owner], dict)
               or not isinstance(inventory[owner].get("count"), int)
               or inventory[owner]["count"] < 1 for owner in item["owners"]):
            raise ValueError("owner absent from default inventory")
    return isolated


def _docs(path: str) -> bool:
    return path in DOC_FILES or (path.startswith(("PRD/", "docs/")) and path.endswith(".md"))


def select_plan(changes: list[tuple[str, str]], root: Path = ROOT) -> dict:
    full = {"mode": "full", "owners": [], "postgres": True, "reason": "shared or unknown change"}
    try:
        mapping = _map(root)
        mapped_tools = {path for _, path in changes if path in mapping}
        permitted_tests = {owner for path in mapped_tools for owner in mapping[path]["owners"]}
        owners: set[str] = set()
        postgres = False
        saw_code = False
        if not changes:
            return full
        for status, path in changes:
            if (status not in ("A", "M") or not path or path.startswith("/") or "\\" in path
                    or "//" in path or "." in Path(path).parts or ".." in Path(path).parts
                    or any(ord(char) < 32 for char in path)):
                return full
            if _docs(path):
                continue
            if path.startswith("tests/") and status == "M" and path in permitted_tests:
                continue
            if path.startswith(PROTECTED) or path not in mapping:
                return full
            saw_code = True
            owners.update(mapping[path]["owners"])
            postgres |= mapping[path]["postgres"]
        if not saw_code or not owners:
            return full
        return {"mode": "isolated", "owners": sorted(owners), "postgres": postgres,
                "reason": "mapped isolated files"}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return full


def git_changes(base: str) -> list[tuple[str, str]]:
    if len(base) != 40 or any(char not in "0123456789abcdef" for char in base):
        raise ValueError("invalid base SHA")
    raw = subprocess.run(["git", "diff", "--no-renames", "--name-status", "-z", base, "HEAD"],
                         check=True, capture_output=True).stdout
    parts = raw.split(b"\0")
    if not raw or parts[-1] or len(parts) % 2 != 1:
        raise ValueError("invalid diff")
    return [(parts[i].decode(), parts[i + 1].decode()) for i in range(0, len(parts) - 1, 2)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--event", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = select_plan(git_changes(args.base)) if args.event == "pull_request" else {
            "mode": "full", "owners": [], "postgres": True, "reason": "main or manual"}
    except (ValueError, OSError, subprocess.CalledProcessError, UnicodeError):
        plan = {"mode": "full", "owners": [], "postgres": True, "reason": "invalid diff"}
    args.output.write_text(json.dumps(plan, sort_keys=True) + "\n")
    print(json.dumps(plan, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

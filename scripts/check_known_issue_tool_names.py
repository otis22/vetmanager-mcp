#!/usr/bin/env python3
"""Check that seeded known issues reference registered MCP tool names."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tool_access_registry import TOOL_REQUIRED_SCOPES


def _literal_string(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def _related_tool_rule_values(match_rules: Any) -> list[str]:
    if not isinstance(match_rules, dict):
        return []
    conditions = match_rules.get("all")
    if not isinstance(conditions, list):
        return []
    values: list[str] = []
    for condition in conditions:
        if not isinstance(condition, dict) or condition.get("field") != "related_tool":
            continue
        op = condition.get("op")
        value = condition.get("value")
        if op == "eq" and isinstance(value, str):
            values.append(value)
        elif op == "in" and isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return values


def _rule_values_from_node(node: ast.AST, constants: dict[str, str]) -> tuple[list[str], bool]:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "_rules" and node.args:
            tool_name = _literal_string(node.args[0], constants)
            return ([tool_name], True) if tool_name else ([], False)
        if node.func.id == "_text_rules":
            for keyword in node.keywords:
                if keyword.arg == "tool":
                    tool_name = _literal_string(keyword.value, constants)
                    return ([tool_name], True) if tool_name else ([], False)
            return [], True
    try:
        return _related_tool_rule_values(ast.literal_eval(node)), True
    except (ValueError, SyntaxError):
        return [], False


def _seed_issues_from_path(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                value = _literal_string(node.value, constants)
                if value is not None:
                    constants[target.id] = value

    issues: list[dict[str, Any]] = []
    found_seed_issues = False
    for node in tree.body:
        value_node: ast.AST | None = None
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "SEED_ISSUES" for target in node.targets):
                value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "SEED_ISSUES":
            value_node = node.value
        if value_node is None:
            continue
        found_seed_issues = True
        if not isinstance(value_node, (ast.Tuple, ast.List)):
            issues.append({
                "slug": "<module>",
                "related_tool": None,
                "related_tool_parsed": True,
                "rule_tools": [],
                "rules_parsed": False,
            })
            continue
        for item in value_node.elts:
            if not isinstance(item, ast.Call):
                issues.append({
                    "slug": "<unknown>",
                    "related_tool": None,
                    "related_tool_parsed": False,
                    "rule_tools": [],
                    "rules_parsed": False,
                })
                continue
            issue: dict[str, Any] = {
                "slug": "<unknown>",
                "related_tool": None,
                "related_tool_parsed": True,
                "rule_tools": [],
                "rules_parsed": True,
            }
            for keyword in item.keywords:
                if keyword.arg == "slug":
                    issue["slug"] = _literal_string(keyword.value, constants) or "<unknown>"
                elif keyword.arg == "related_tool":
                    if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                        issue["related_tool"] = None
                    else:
                        related_tool = _literal_string(keyword.value, constants)
                        issue["related_tool"] = related_tool
                        issue["related_tool_parsed"] = related_tool is not None
                elif keyword.arg == "match_rules":
                    issue["rule_tools"], issue["rules_parsed"] = _rule_values_from_node(
                        keyword.value,
                        constants,
                    )
            issues.append(issue)
    if not found_seed_issues or not issues:
        issues.append({
            "slug": "<module>",
            "related_tool": None,
            "related_tool_parsed": False,
            "rule_tools": [],
            "rules_parsed": False,
        })
    return issues


def find_errors(seed_issues: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for issue in seed_issues:
        slug = issue["slug"]
        related_tool = issue["related_tool"]
        if not issue["related_tool_parsed"]:
            errors.append(f"[seed:{slug}] related_tool could not be parsed")
        if not issue["rules_parsed"]:
            errors.append(f"[seed:{slug}] match_rules could not be parsed")
        if related_tool and related_tool not in TOOL_REQUIRED_SCOPES:
            errors.append(f"[seed:{slug}] related_tool {related_tool!r} is not registered")
        for tool_name in issue["rule_tools"]:
            if tool_name not in TOOL_REQUIRED_SCOPES:
                errors.append(
                    f"[seed:{slug}] match_rules related_tool {tool_name!r} is not registered"
                )
    return errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate known-issue seed tool names against TOOL_REQUIRED_SCOPES."
    )
    parser.add_argument(
        "--seed-module-path",
        type=Path,
        default=None,
        help="Optional Python module path exposing SEED_ISSUES, for tests.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    seed_path = args.seed_module_path or ROOT / "scripts" / "seed_known_issues.py"
    errors = find_errors(_seed_issues_from_path(seed_path))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

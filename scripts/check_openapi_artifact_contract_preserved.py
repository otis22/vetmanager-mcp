#!/usr/bin/env python3
"""Verify Stage 164 OpenAPI structure stayed unchanged after value sanitization."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


OPENAPI_ARTIFACT = Path("artifacts/vetmanager_openapi_v6.json")
BASELINE_ARTIFACT = Path("artifacts/security/stage-164-openapi-structure-baseline.json")
PASSWD_SCHEMA_PATH = ("components", "schemas", "user", "properties", "passwd")
PASSWD_VALUE_KEY = "passwd"
FORBIDDEN_PASSWD_CONSTRAINTS = ("pattern", "format", "minLength", "maxLength")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def scalar_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    raise TypeError(f"not a scalar: {type(value).__name__}")


def iter_structure(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    if isinstance(value, dict):
        keys = sorted(value)
        rows = [f"{'.'.join(path)}|object|{','.join(keys)}"]
        for key in keys:
            rows.extend(iter_structure(value[key], (*path, key)))
        return rows
    if isinstance(value, list):
        rows = [f"{'.'.join(path)}|array|{len(value)}"]
        for index, item in enumerate(value):
            rows.extend(iter_structure(item, (*path, str(index))))
        return rows
    return [f"{'.'.join(path)}|scalar|{scalar_type(value)}"]


def structural_fingerprint(value: Any) -> dict[str, Any]:
    rows = iter_structure(value)
    payload = "\n".join(rows).encode("utf-8")
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "entries": len(rows),
        "objects": sum("|object|" in row for row in rows),
        "arrays": sum("|array|" in row for row in rows),
        "scalars": sum("|scalar|" in row for row in rows),
    }


def get_path(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for part in path:
        current = current[part]
    return current


def iter_key_values(value: Any, target_key: str, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    matches: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if key == target_key:
                matches.append((child_path, child))
            matches.extend(iter_key_values(child, target_key, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(iter_key_values(child, target_key, (*path, str(index))))
    return matches


def passwd_schema_context(value: Any) -> dict[str, Any]:
    schema = get_path(value, PASSWD_SCHEMA_PATH)
    example = schema.get("example")
    return {
        "path": ".".join(PASSWD_SCHEMA_PATH),
        "type": schema.get("type"),
        "x-db-type": schema.get("x-db-type"),
        "example_type": scalar_type(example),
        "example_length": len(example) if isinstance(example, str) else None,
        "forbidden_constraints_present": sorted(
            key for key in FORBIDDEN_PASSWD_CONSTRAINTS if key in schema
        ),
    }


def build_baseline(openapi: Any, source_git_sha: str) -> dict[str, Any]:
    return {
        "stage": 164,
        "artifact": str(OPENAPI_ARTIFACT),
        "source_git_sha": source_git_sha,
        "structural_fingerprint": structural_fingerprint(openapi),
        "passwd_schema_context": passwd_schema_context(openapi),
    }


def check_contract(openapi: Any, baseline: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    current_fingerprint = structural_fingerprint(openapi)
    expected_fingerprint = baseline.get("structural_fingerprint")
    if current_fingerprint != expected_fingerprint:
        errors.append("OpenAPI structural fingerprint differs from Stage 164 baseline")

    current_context = passwd_schema_context(openapi)
    expected_context = baseline.get("passwd_schema_context")
    if current_context != expected_context:
        errors.append("passwd schema context differs from Stage 164 baseline")

    if current_context.get("type") != "string":
        errors.append("passwd schema type is not string")
    if current_context.get("x-db-type") != "varchar(32)":
        errors.append("passwd schema x-db-type is not varchar(32)")
    if current_context.get("example_type") != "str":
        errors.append("passwd schema example is not string")
    if current_context.get("example_length") != 32:
        errors.append("passwd schema example does not preserve 32-character shape")
    if current_context.get("forbidden_constraints_present"):
        errors.append("passwd schema has pattern/format/minLength/maxLength constraints")

    for path, value in iter_key_values(openapi, PASSWD_VALUE_KEY):
        if path == PASSWD_SCHEMA_PATH:
            continue
        if not isinstance(value, str):
            errors.append(f"{'.'.join(path)} is not a string")
        elif len(value) != 32:
            errors.append(f"{'.'.join(path)} does not preserve 32-character shape")

    return errors


def main(repo_root: Path | None = None) -> int:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[1]

    openapi = load_json(repo_root / OPENAPI_ARTIFACT)
    baseline = load_json(repo_root / BASELINE_ARTIFACT)
    errors = check_contract(openapi, baseline)
    if errors:
        print("stage164 OpenAPI contract preservation check failed:", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print("stage164 OpenAPI contract preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Require every mandatory PostgreSQL regression to have actually passed."""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


REQUIRED_FILES = frozenset({
    "test_stage227_postgres_activation_telemetry",
    "test_stage359_postgres_activation_journal",
    "test_stage374_first_session",
    "test_stage376_expiry_notice",
    "test_stage385_cache_barrier",
    "test_vetmanager_connection_service",
})


def validate_results(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("PostgreSQL JUnit XML has no executed testcases")

    names = []
    passed_files = set()
    for case in cases:
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        names.append(name)
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error")):
            raise ValueError(f"PostgreSQL testcase did not pass: {name}")
        file = case.get("classname", "").rsplit(".", 1)[-1]
        if file in REQUIRED_FILES:
            passed_files.add(file)

    missing = REQUIRED_FILES - passed_files
    if missing:
        raise ValueError(f"Mandatory PostgreSQL files missing from executed results: {sorted(missing)}")
    return names


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_stage424_postgres_results.py JUNIT_XML", file=sys.stderr)
        return 2
    try:
        names = validate_results(Path(sys.argv[1]))
    except (ET.ParseError, OSError, ValueError) as exc:
        print(f"PostgreSQL result gate failed: {exc}", file=sys.stderr)
        return 1
    for name in names:
        print(f"PostgreSQL passed: {name}")
    print(f"PostgreSQL result gate passed: {len(names)} tests; all mandatory files present; 0 skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

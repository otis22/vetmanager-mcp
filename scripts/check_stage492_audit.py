#!/usr/bin/env python3
"""Fail closed on incomplete pip-audit output or unreviewed advisories."""
import json
import re
import sys
from datetime import date
from pathlib import Path

KNOWN = {
    ("cryptography", "46.0.7", item) for item in (
        "PYSEC-2026-3552", "PYSEC-2026-3553", "PYSEC-2026-3554",
        "GHSA-537c-gmf6-5ccf")
}
EXPIRES = date(2026, 12, 22)


def package_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def parse_freeze(freeze_path: Path) -> dict[str, str]:
    freeze = {}
    for line in freeze_path.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+\-]+)", line.strip())
        if not match:
            raise ValueError("invalid pip freeze entry")
        name = package_name(match[1])
        if name in freeze:
            raise ValueError("duplicate package in freeze")
        freeze[name] = match[2]
    if not freeze:
        raise ValueError("empty freeze")
    return freeze


def verify(freeze_path: Path, report_path: Path, *, today: date | None = None) -> None:
    if (today or date.today()) >= EXPIRES:
        raise ValueError("temporary known-finding policy expired")
    freeze = parse_freeze(freeze_path)
    report = json.loads(report_path.read_text())
    deps = report.get("dependencies")
    if not freeze or not isinstance(deps, list) or not deps:
        raise ValueError("empty scan")
    seen = {}
    findings = set()
    for dep in deps:
        if not isinstance(dep, dict) or not isinstance(dep.get("vulns"), list):
            raise ValueError("incomplete scan dependency")
        name, version = package_name(dep["name"]), dep["version"]
        if name in seen or not isinstance(version, str):
            raise ValueError("duplicate or invalid scan dependency")
        seen[name] = version
        for vuln in dep["vulns"]:
            if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str) or not vuln["id"]:
                raise ValueError("invalid advisory")
            findings.add((name, version, vuln["id"]))
    if seen != freeze:
        raise ValueError("audit inventory differs from production freeze")
    print(json.dumps({"packages": len(seen), "known": sorted(KNOWN & findings),
                      "new": sorted(findings - KNOWN), "missing_known": sorted(KNOWN - findings),
                      "policy_expires": EXPIRES.isoformat()}, ensure_ascii=False))
    if findings != KNOWN:
        raise ValueError("advisory set differs from reviewed temporary policy")


if __name__ == "__main__":
    try:
        verify(Path(sys.argv[1]), Path(sys.argv[2]))
    except (IndexError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"stage492 audit blocked: {exc}", file=sys.stderr)
        sys.exit(1)

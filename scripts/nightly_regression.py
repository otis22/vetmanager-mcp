#!/usr/bin/env python3
"""Run nightly contours sequentially and export only allowlisted triage data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts/real_group_manifest.json"
COUNTS = ("passed", "failed", "skipped-not-configured", "skipped-error")


def blocks_upstream(group: str, exit_code: int, summary: dict | None,
                    *, evidence_complete: bool = True) -> bool:
    """A failed write or unverified cleanup makes later live work unsafe."""
    if (not evidence_complete or not isinstance(summary, dict)
            or not isinstance(summary.get("results"), dict)):
        return True
    results = summary["results"]
    if results.get("cleanup") != 0:
        return True
    return group == "write-restore" and exit_code != 0


def final_exit(results: dict[str, int], *, aggregate: int,
               required: set[str] | None = None) -> int:
    return int(aggregate != 0 or not results or
               (required is not None and not required <= results.keys()) or
               any(code != 0 for code in results.values()))


def same_image(expected: str) -> bool:
    try:
        current = subprocess.run(["docker", "image", "inspect", "vetmanager-mcp-test",
                                  "--format", "{{.Id}}"], capture_output=True, text=True)
    except OSError:
        return False
    return current.returncode == 0 and current.stdout.strip() == expected


def group_from_evidence(directory: str, groups: dict) -> str | None:
    return max((name for name in groups if directory.startswith(name + "-")),
               key=len, default=None)


def group_artifact_source(root: Path, group: str, groups: dict) -> Path | None:
    matches = [entry for entry in root.iterdir() if entry.is_dir()
               and group_from_evidence(entry.name, groups) == group]
    return matches[0] if len(matches) == 1 else None


def offline_cleanup_ok(directory: Path) -> bool:
    try:
        summary = json.loads((directory / "summary.json").read_text())
        return (summary.get("results", {}).get("cleanup") == 0
                and (directory / "cleanup.log").is_file())
    except (OSError, ValueError, AttributeError):
        return False


def expected_cases(allowed: set[str]) -> dict[tuple[str, str], str]:
    expected = {}
    for node in allowed:
        file, sep, rest = node.partition("::")
        if not sep or not file.startswith("tests/") or not file.endswith(".py"):
            raise ValueError("invalid allowed node")
        base, bracket, parameter = rest.partition("[")
        parts = base.split("::")
        classname = file[:-3].replace("/", ".")
        if len(parts) > 1:
            classname += "." + ".".join(parts[:-1])
        name = parts[-1] + (bracket + parameter if bracket else "")
        expected[(classname, name)] = node
    if len(expected) != len(allowed):
        raise ValueError("ambiguous allowed node")
    return expected


def sanitize_junit(source: Path, target: Path, allowed: set[str]) -> None:
    """Keep static node ID and status; discard all arbitrary upstream text."""
    tree = ET.parse(source)
    cases = list(tree.getroot().iter("testcase"))
    if not cases:
        raise ValueError("empty JUnit")
    safe_root = ET.Element("testsuites")
    suite = ET.SubElement(safe_root, "testsuite")
    expected = expected_cases(allowed)
    seen = set()
    for case in cases:
        identity = (case.get("classname", ""), case.get("name", ""))
        name = expected.get(identity)
        if name is None or name in seen:
            raise ValueError("unknown or duplicate JUnit node")
        seen.add(name)
        safe = ET.SubElement(suite, "testcase", classname=identity[0], name=identity[1])
        for tag in ("failure", "error", "skipped"):
            if case.find(tag) is not None:
                ET.SubElement(safe, tag)
    if seen != allowed:
        raise ValueError("incomplete JUnit")
    ET.ElementTree(safe_root).write(target, encoding="unicode")


def sanitize_offline(contour: str, raw: Path, nodes_file: Path,
                     gate: Path | None, target: Path) -> None:
    allowed = json.loads(nodes_file.read_text())
    if not isinstance(allowed, list) or len(allowed) != len(set(allowed)):
        raise ValueError("invalid offline manifest nodes")
    if gate is not None:
        record = json.loads(gate.read_text())
        if (record.get("contour") != contour or record.get("complete") is not True
                or set(record.get("nodes", [])) != set(allowed)):
            raise ValueError("offline manifest missing or incomplete")
    sanitize_junit(raw, target, set(allowed))


def sanitize_outcome(source: Path, target: Path, allowed: set[str]) -> None:
    raw = json.loads(source.read_text())
    nodes = raw.get("nodes")
    counts = raw.get("counts")
    if (not isinstance(nodes, dict) or set(nodes) != allowed
            or any(value not in {"passed", "failed", "skipped-not-configured", "skipped-error"}
                   for value in nodes.values())
            or not isinstance(counts, dict) or any(type(counts.get(key)) is not int
                                                    or counts[key] < 0 for key in COUNTS)
            or raw.get("collected") != len(allowed)):
        raise ValueError("invalid outcome")
    target.write_text(json.dumps({"collected": raw["collected"],
                                  "counts": {key: counts[key] for key in COUNTS},
                                  "nodes": nodes}, sort_keys=True) + "\n")


def group_evidence_complete(directory: Path, group: str, allowed: set[str],
                            image_id: str, exit_code: int) -> bool:
    """Only a complete ordinary test failure is safe to continue past."""
    try:
        shard = json.loads((directory / "shard.json").read_text())
        outcome = json.loads((directory / f"{group}.outcome.json").read_text())
        cases = list(ET.parse(directory / f"{group}.xml").getroot().iter("testcase"))
        expected = expected_cases(allowed)
        identities = [(case.get("classname"), case.get("name")) for case in cases]
        junit_status = {expected[identity]: ("failed" if case.find("failure") is not None
                         or case.find("error") is not None else "passed")
                        for identity, case in zip(identities, cases) if identity in expected}
        counts = outcome["counts"]
        return (shard.get("group") == group and set(shard.get("nodes", [])) == allowed
                and len(shard["nodes"]) == len(allowed) and shard.get("image_id") == image_id
                and shard.get("results", {}).get("cleanup") == 0
                and (shard["results"].get("test") == 0) == (exit_code == 0)
                and outcome.get("collected") == len(allowed)
                and set(outcome.get("nodes", {})) == allowed
                and set(outcome["nodes"].values()) <= {"passed", "failed"}
                and all(type(counts.get(key)) is int and counts[key] >= 0 for key in COUNTS)
                and counts["skipped-not-configured"] == counts["skipped-error"] == 0
                and (exit_code == 0 or counts["failed"] > 0)
                and sum(counts[key] for key in COUNTS) == len(allowed)
                and len(identities) == len(allowed) and set(identities) == set(expected)
                and all(case.find("skipped") is None for case in cases)
                and junit_status == outcome["nodes"]
                and counts["passed"] == sum(status == "passed" for status in junit_status.values())
                and counts["failed"] == sum(status == "failed" for status in junit_status.values()))
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
        return False


def run_command(label: str, command: list[str], private: Path, results: dict) -> int:
    started = time.monotonic()
    with (private / f"{label}.log").open("w") as log:
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   check=False)
    results[label] = {"exit": completed.returncode, "seconds": round(time.monotonic() - started)}
    print(f"{label}: exit {completed.returncode}; {results[label]['seconds']}s", flush=True)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    private = args.evidence_dir.resolve()
    if private == ROOT or ROOT in private.parents or private.exists():
        parser.error("evidence must be a new directory outside checkout")
    private.mkdir(mode=0o700, parents=True)
    public = private / "artifact"
    public.mkdir(mode=0o700)
    results = {}
    codes = {}
    aggregate = 1
    manifest = json.loads(MANIFEST.read_text())
    groups = manifest["groups"]
    group_root = private / "real"
    group_root.mkdir(mode=0o700)
    try:
        image = subprocess.run(["docker", "image", "inspect", "vetmanager-mcp-test",
                                "--format", "{{.Id}}"], capture_output=True, text=True)
        image_id = image.stdout.strip() if image.returncode == 0 else ""
    except OSError:
        image_id = ""
    required = ("TEST_DOMAIN", "TEST_API_KEY", "TEST_USER_LOGIN", "TEST_USER_PASSWORD")
    missing = [name for name in required if not os.environ.get(name)]
    if missing or not image_id.startswith("sha256:"):
        print("nightly preflight: missing required test settings or test image", file=sys.stderr)
        codes["preflight"] = 1
    else:
        os.environ["UID"] = str(os.getuid())
        os.environ["GID"] = str(os.getgid())
        (group_root / "test-image.id").write_text(image_id + "\n")
        base = [sys.executable, "scripts/run_isolated_test_suite.py"]
        codes["inventory"] = run_command("inventory", ["docker", "run", "--rm",
            "-v", f"{ROOT}:/app", "-v", f"{private}:/evidence",
            "-u", f"{os.getuid()}:{os.getgid()}", "vetmanager-mcp-test",
            "sh", "-c", "python scripts/offline_gate_manifest.py default --check-inventory "
            "--output-nodes /evidence/default-nodes.json && "
            "python scripts/offline_gate_manifest.py postgres --check-inventory "
            "--output-nodes /evidence/postgres-nodes.json"], private, results)
        if codes["inventory"] == 0:
            codes["default"] = run_command("default", [*base, "--suite", "default",
                "--evidence-dir", str(private / "default")], private, results)
            codes["postgres"] = run_command("postgres", [*base, "--suite", "postgres",
                "--evidence-dir", str(private / "postgres")], private, results)
            if not same_image(image_id):
                codes["image"] = 1
            for contour in ("default", "postgres"):
                raw = private / contour / f"{contour}.xml"
                if raw.exists():
                    try:
                        gate = (ROOT / ".stage465-default-gate.json" if contour == "default"
                                else private / "postgres/postgres-gate.json")
                        sanitize_offline(contour, raw, private / f"{contour}-nodes.json",
                                         gate if codes[contour] == 0 else None,
                                         public / f"{contour}.xml")
                    except (OSError, ValueError, ET.ParseError):
                        codes["artifact"] = 1
            unsafe = (codes.get("image") == 1
                      or not offline_cleanup_ok(private / "default")
                      or not offline_cleanup_ok(private / "postgres"))
            for group in groups:
                if unsafe:
                    codes[group] = 1
                    results[group] = {"exit": 1, "status": "blocked"}
                    continue
                code = run_command(group, [*base, "--suite", "real", "--group", group,
                    "--evidence-dir", str(group_root)], private, results)
                codes[group] = code
                index = group_root / "attempts.jsonl"
                try:
                    latest = [json.loads(line) for line in index.read_text().splitlines()][-1]
                    evidence = group_root / latest["directory"]
                    summary = json.loads((evidence / "summary.json").read_text())
                    complete = group_evidence_complete(evidence, group, set(groups[group]),
                                                       image_id, code)
                except (OSError, ValueError, KeyError, IndexError):
                    summary = None
                    complete = False
                unsafe = blocks_upstream(group, code, summary, evidence_complete=complete)
                if not same_image(image_id):
                    codes["image"] = 1
                    unsafe = True
            aggregate = run_command("aggregate", [*base, "--aggregate", "--evidence-dir",
                str(group_root)], private, results)
            codes["aggregate"] = aggregate
            for group in groups:
                if results.get(group, {}).get("status") == "blocked":
                    continue
                entry = group_artifact_source(group_root, group, groups)
                if entry is None:
                    codes["artifact"] = 1
                    continue
                allowed = set(groups[group])
                for suffix, sanitizer in (("xml", sanitize_junit), ("outcome.json", sanitize_outcome)):
                    source = entry / f"{group}.{suffix}"
                    try:
                        sanitizer(source, public / f"{group}.{suffix}", allowed)
                    except (OSError, ValueError, ET.ParseError):
                        codes["artifact"] = 1
    outcome = final_exit(codes, aggregate=aggregate,
                         required={"inventory", "default", "postgres", *groups})
    summary = {"groups": results, "result": "failed" if outcome else "passed"}
    lines = ["## Nightly regression", "", "| Contour | Exit | Seconds | Status |", "| --- | ---: | ---: | --- |"]
    for name, item in results.items():
        lines.append(f"| {name} | {item['exit']} | {item.get('seconds', '-')} | {item.get('status', 'completed')} |")
    lines.append(f"\nResult: **{summary['result']}**")
    (private / "summary.md").write_text("\n".join(lines) + "\n")
    if codes.get("artifact") == 1:
        shutil.rmtree(public)
    else:
        (public / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
        (public / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"Nightly result: {summary['result']}; artifact ready: {public.is_dir()}", flush=True)
    return outcome


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate measured three-slot stage 385 load evidence."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys


MIB = 1024 ** 2
MCP_SLOT_CAP = 640 * MIB
MCP_FLEET_LIMIT = 2 * 1024 ** 3
STOP_THRESHOLD = int(.7 * MCP_FLEET_LIMIT)


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(report: dict) -> list[str]:
    errors = []
    if report.get("calls") != 200 or report.get("metric_delta") != 200:
        errors.append("Expected 200 calls and a shared metric delta of 200")
    slots = report.get("per_slot")
    if (not isinstance(slots, dict) or len(slots) != 3
            or not all(isinstance(value, int) and value > 0 for value in slots.values())
            or sum(slots.values()) != 200):
        errors.append("Expected 200 calls distributed across three slots")
    if report.get("http_codes") != {"200": 200} or report.get("safe_bodies") != {
        "tool_error": False, "rpc_error": False,
    }:
        errors.append("Expected only successful HTTP and MCP results")
    if not _number(report.get("p95_ms")) or report["p95_ms"] <= 0:
        errors.append("p95 timing is missing")
    if report.get("threshold_bytes") != STOP_THRESHOLD:
        errors.append("70% of the 2 GiB fleet cap was not used")

    after = report.get("after")
    before = report.get("before")
    if not isinstance(after, dict) or not isinstance(before, dict):
        return errors + ["Both before and after measurements are required"]
    for phase, values in (("before", before), ("after", after)):
        for field in ("head_series", "head_chunks", "redis_memory", "pg_sessions"):
            if not _number(values.get(field)) or values[field] < 0:
                errors.append(f"{phase}.{field} is missing")
        if _number(values.get("redis_memory")) and values["redis_memory"] > 512 * MIB:
            errors.append(f"{phase} Redis memory exceeded its cap")
        if _number(values.get("pg_sessions")) and values["pg_sessions"] > 40:
            errors.append(f"{phase} PostgreSQL session budget exceeded 40")
        cgroups = values.get("cgroup")
        if not isinstance(cgroups, list) or len(cgroups) != 3:
            errors.append(f"{phase} must contain three cgroup measurements")
            continue
        for slot in cgroups:
            if not isinstance(slot, dict) or not all(_number(slot.get(field)) for field in (
                    "rss_peak_bytes", "cgroup_peak_bytes", "cgroup_current_bytes",
                    "oom", "cap_bytes", "cpu_limit")):
                errors.append(f"{phase} has an incomplete slot measurement")
                continue
            if slot["oom"] != 0:
                errors.append(f"{phase} contains an OOM event")
            if slot["cap_bytes"] > MCP_SLOT_CAP or slot["cap_bytes"] <= 0:
                errors.append(f"{phase} exceeds the 640 MiB slot cap")
            if slot["cpu_limit"] > 1 or slot["cpu_limit"] <= 0:
                errors.append(f"{phase} exceeds the one CPU slot cap")
            if slot["cgroup_peak_bytes"] > slot["cap_bytes"]:
                errors.append(f"{phase} cgroup peak exceeds its slot cap")
        if all(isinstance(slot, dict) and _number(slot.get("cgroup_peak_bytes"))
               for slot in cgroups) and sum(slot["cgroup_peak_bytes"] for slot in cgroups) > STOP_THRESHOLD:
            errors.append(f"{phase} aggregate cgroup peak exceeds 70% of 2 GiB")
    if _number(after.get("head_series")) and after["head_series"] <= 0:
        errors.append("Prometheus must have scraped at least one series")
    cgroups = after.get("cgroup")
    if (isinstance(cgroups, list) and len(cgroups) == 3
            and all(isinstance(slot, dict) and _number(slot.get("rss_peak_bytes"))
                    for slot in cgroups)):
        formula = sum(slot["rss_peak_bytes"] for slot in cgroups) + 512 * MIB
        if report.get("rss_formula_bytes") != formula:
            errors.append("RSS plus 512 MiB formula is inconsistent with slot measurements")
        if formula > STOP_THRESHOLD:
            errors.append("RSS plus 512 MiB exceeds 70% of 2 GiB")
    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: check_stage385_resource_gate.py <evidence.json>")
    problems = validate(json.loads(Path(sys.argv[1]).read_text()))
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        raise SystemExit(1)
    print("stage385 resource gate: pass")

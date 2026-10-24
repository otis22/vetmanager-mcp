"""Pytest plugin loaded only by the opt-in real suite runner."""

from __future__ import annotations

import json
import os
from pathlib import Path

_skipif_reasons: dict[str, set[str]] = {}
_results: dict[str, str] = {}
_collected = 0
_collection_errors = 0


def pytest_collection_finish(session):
    global _collected
    _collected = len(session.items)
    for item in session.items:
        _skipif_reasons[item.nodeid] = {
            mark.kwargs.get("reason", "")
            for mark in item.iter_markers("skipif")
            if mark.args and isinstance(mark.args[0], bool) and mark.args[0]
        }


def pytest_runtest_logreport(report):
    if report.failed:
        _results[report.nodeid] = "failed"
    elif report.passed and report.when == "call":
        if _results.get(report.nodeid) != "failed":
            _results[report.nodeid] = "passed"
    elif report.skipped and _results.get(report.nodeid) != "failed":
        reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
        if report.when == "setup" and any(
            marker_reason and reason.endswith(marker_reason)
            for marker_reason in _skipif_reasons.get(report.nodeid, ())
        ):
            _results[report.nodeid] = "skipped-not-configured"
        else:
            _results[report.nodeid] = "skipped-error"


def pytest_collectreport(report):
    global _collection_errors
    if report.failed:
        _collection_errors += 1


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("PYTEST_REAL_OUTCOME_FILE")
    if path:
        counts = {key: sum(value == key for value in _results.values()) for key in (
            "passed", "failed", "skipped-not-configured", "skipped-error")}
        counts["failed"] += _collection_errors
        Path(path).write_text(json.dumps({
            "collected": _collected,
            "counts": counts,
            "not_configured": [key for key, value in _results.items() if value == "skipped-not-configured"],
            "skip_errors": [key for key, value in _results.items() if value == "skipped-error"],
        }, sort_keys=True), encoding="utf-8")

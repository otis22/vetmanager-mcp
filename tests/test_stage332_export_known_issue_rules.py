"""Этап 332: каждый финальный отказ экспорта получает правильный playbook."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_feedback_service as feedback
from exceptions import VetmanagerError
from storage_models import KnownIssue
from tools import report_ai


FIXTURES = Path(__file__).parents[1] / "artifacts" / "known-issues" / "stage-332"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _error(exc: BaseException) -> str:
    return str(exc)


FAILURES = (
    ("start_report_export", _error(report_ai._safe_export_error(
        VetmanagerError("Report creating in progress", 403), "Starting report export")), "ki45"),
    ("start_report_export", _error(report_ai._safe_export_error(
        VetmanagerError("can not run a report more than 10 minutes", 403), "Starting report export")), "ki45"),
    ("start_report_export", _error(report_ai._safe_export_error(
        VetmanagerError("not accessible for rest", 403), "Starting report export",
        report_id_from_caller=True)), "ki45"),
    ("start_report_export", _error(report_ai._safe_export_error(
        VetmanagerError("unexpected refusal", 403), "Starting report export")), "ki45"),
    ("start_report_export", _error(report_ai._safe_export_error(
        VetmanagerError("upstream failed", 500), "Starting report export")), "ki45"),
    ("start_report_export", "Starting report export failed.", "ki45"),
    ("start_report_export", "Starting report export failed: report_file_id is missing.", "ki45"),
    ("get_report_export_download", _error(report_ai._safe_export_error(
        VetmanagerError("build in progress", 401), "Getting report export file",
        retry_on_conflict=True)), "ki45"),
    ("get_report_export_download", _error(report_ai._safe_export_error(
        VetmanagerError("not started", 401), "Getting report export file",
        retry_on_conflict=True)), "ki45"),
    ("get_report_export_download", _error(report_ai._safe_export_error(
        VetmanagerError("conflict", 409), "Getting report export file",
        retry_on_conflict=True)), "ki45"),
    ("get_report_export_download", _error(report_ai._safe_export_error(
        VetmanagerError("unauthorized", 401), "Getting report export file",
        retry_on_conflict=True)), "download401"),
    ("get_report_export_download", _error(report_ai._safe_export_error(
        VetmanagerError("missing", 404), "Getting report export file",
        retry_on_conflict=True)), "ki45"),
    ("get_report_export_download", "Getting report export file failed.", "ki45"),
    ("get_report_export_download", "Getting report export file failed: export file fields are missing.", "ki45"),
    ("get_report_export_download", "MCP observed this export still not ready for 30 minutes. Stop automatic polling and do not start a new export: this same build may still finish.", "ki45"),
)


@pytest.mark.parametrize(("tool", "message", "expected"), FAILURES)
def test_every_export_failure_matches_exactly_one_versioned_issue(tool, message, expected):
    for text in (message, f"Error calling tool '{tool}': {message}"):
        incident = feedback.build_incident_from_exception(tool, RuntimeError(text))
        matches = {
            name
            for name, filename in (
                ("ki45", "ki45-match-rules.json"),
                ("download401", "download-401-match-rules.json"),
            )
            if feedback.match_rules(json.dumps(_load(filename)), incident)
        }
        assert matches == {expected}


def test_versioned_rules_and_playbooks_pass_production_validators():
    for filename in ("ki45-match-rules.json", "download-401-match-rules.json"):
        assert feedback.validate_match_rules_json(
            json.dumps(_load(filename)), strict_tool_names=True
        ) is not None
    for filename in ("ki45-playbook.json", "download-401-playbook.json"):
        assert feedback.validate_agent_playbook(json.dumps(_load(filename))) is not None


@pytest.mark.asyncio
async def test_moved_report_80_fingerprint_selects_download_401_issue(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage332-test-pepper")
    factory = await sqlite_session_factory_builder(tmp_path / "stage332.db")
    incident = feedback.build_incident_from_exception(
        "get_report_export_download",
        RuntimeError("Getting report export file failed HTTP 401."),
    )
    fingerprint = feedback.build_error_fingerprint_hash(incident)
    async with factory() as session:
        ki45 = KnownIssue(
            status="workaround_available", category="bug", severity="medium",
            title="KI-45", related_tool=None, error_fingerprint_hash=None,
            match_rules_json=json.dumps(_load("ki45-match-rules.json")),
            agent_playbook_json=json.dumps(_load("ki45-playbook.json")),
        )
        download = KnownIssue(
            status="workaround_available", category="bug", severity="medium",
            title="download 401", related_tool="get_report_export_download",
            error_fingerprint_hash=fingerprint,
            match_rules_json=json.dumps(_load("download-401-match-rules.json")),
            agent_playbook_json=json.dumps(_load("download-401-playbook.json")),
        )
        session.add_all([ki45, download])
        await session.commit()
        match = await feedback.find_known_issue_match(session, incident)

    assert match is not None
    assert match.id == download.id
    assert match.playbook["safe_to_retry"] is False

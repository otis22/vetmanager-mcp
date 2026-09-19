"""Этап 332: fingerprint переносится между известными проблемами атомарно."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.triage_agent_feedback as triage
from storage_models import KnownIssue


def _issue(title: str, fingerprint: str | None) -> KnownIssue:
    return KnownIssue(
        status="workaround_available", category="bug", severity="medium",
        title=title, error_fingerprint_hash=fingerprint,
    )


@pytest.mark.asyncio
async def test_move_fingerprint_accepts_promote_duplicate_and_is_reversible(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "move.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: factory)
    async with factory() as session:
        source = _issue("KI-45", "same-hash")
        target = _issue("download 401", "same-hash")
        session.add_all([source, target])
        await session.commit()
        source_id, target_id = source.id, target.id

    await triage._move_fingerprint(SimpleNamespace(source_id=source_id, target_id=target_id))
    async with factory() as session:
        source = await session.get(KnownIssue, source_id)
        target = await session.get(KnownIssue, target_id)
        assert (source.error_fingerprint_hash, target.error_fingerprint_hash) == (None, "same-hash")

    await triage._move_fingerprint(SimpleNamespace(source_id=target_id, target_id=source_id))
    async with factory() as session:
        source = await session.get(KnownIssue, source_id)
        target = await session.get(KnownIssue, target_id)
        assert (source.error_fingerprint_hash, target.error_fingerprint_hash) == ("same-hash", None)


@pytest.mark.asyncio
async def test_move_fingerprint_rejects_mismatch_without_partial_write(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "mismatch.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: factory)
    async with factory() as session:
        source = _issue("source", "one")
        target = _issue("target", "two")
        session.add_all([source, target])
        await session.commit()
        source_id, target_id = source.id, target.id

    with pytest.raises(SystemExit, match="different fingerprints"):
        await triage._move_fingerprint(SimpleNamespace(source_id=source_id, target_id=target_id))
    async with factory() as session:
        assert (await session.get(KnownIssue, source_id)).error_fingerprint_hash == "one"
        assert (await session.get(KnownIssue, target_id)).error_fingerprint_hash == "two"


@pytest.mark.asyncio
async def test_show_config_is_json_and_does_not_print_report_text(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
):
    factory = await sqlite_session_factory_builder(tmp_path / "show.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: factory)
    async with factory() as session:
        issue = _issue("KI-45", "fingerprint")
        issue.match_rules_json = '{"version": 1, "all": [{"field": "related_tool", "op": "eq", "value": "start_report_export"}]}'
        issue.agent_playbook_json = '{"version": 1, "summary": "safe", "steps": [], "do_not_do": [], "recommended_tool_sequence": [], "safe_to_retry": false}'
        session.add(issue)
        await session.commit()
        issue_id = issue.id

    await triage._show_known_issue_config(SimpleNamespace(known_issue_id=issue_id))
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == issue_id
    assert shown["error_fingerprint_hash"] == "fingerprint"
    assert shown["match_rules_json"]["version"] == 1


def test_parser_exposes_stage332_commands():
    parser = triage._build_parser()
    move = parser.parse_args(["move-fingerprint", "45", "81"])
    show = parser.parse_args(["show-known-issue-config", "45"])
    assert (move.source_id, move.target_id) == (45, 81)
    assert show.known_issue_id == 45

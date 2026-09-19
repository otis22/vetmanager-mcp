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

    move = SimpleNamespace(
        source_id=source_id, target_id=target_id, expected_fingerprint="same-hash"
    )
    await triage._move_fingerprint(move)
    async with factory() as session:
        source = await session.get(KnownIssue, source_id)
        target = await session.get(KnownIssue, target_id)
        assert (source.error_fingerprint_hash, target.error_fingerprint_hash) == (None, "same-hash")

    # Supervisor retry after a partial run must not fail or create another row.
    await triage._move_fingerprint(move)

    await triage._move_fingerprint(SimpleNamespace(
        source_id=target_id, target_id=source_id, expected_fingerprint="same-hash"
    ))
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
async def test_idempotent_move_rejects_an_unrelated_target_fingerprint(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "wrong-target.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: factory)
    async with factory() as session:
        source = _issue("source", None)
        target = _issue("wrong target", "unrelated")
        session.add_all([source, target])
        await session.commit()

    with pytest.raises(SystemExit, match="expected fingerprint"):
        await triage._move_fingerprint(SimpleNamespace(
            source_id=source.id, target_id=target.id, expected_fingerprint="expected"
        ))


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


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True], ids=["nullable", "objects"])
async def test_saved_config_restores_nullable_rules_playbook_and_fingerprint(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys, configured,
):
    factory = await sqlite_session_factory_builder(tmp_path / "restore.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: factory)
    async with factory() as session:
        issue = _issue("KI-45 before", "old-hash")
        original_rules = (
            {"version": 1, "all": [{"field": "related_tool", "op": "eq", "value": "start_report_export"}]}
            if configured else None
        )
        original_playbook = (
            {"version": 1, "summary": "original", "steps": [], "do_not_do": [], "recommended_tool_sequence": [], "safe_to_retry": False}
            if configured else None
        )
        issue.match_rules_json = json.dumps(original_rules) if original_rules else None
        issue.agent_playbook_json = json.dumps(original_playbook) if original_playbook else None
        session.add(issue)
        await session.commit()
        issue_id = issue.id

    await triage._show_known_issue_config(SimpleNamespace(known_issue_id=issue_id))
    snapshot = tmp_path / "before.json"
    snapshot.write_text(capsys.readouterr().out, encoding="utf-8")
    async with factory() as session:
        issue = await session.get(KnownIssue, issue_id)
        issue.title = "changed"
        issue.error_fingerprint_hash = None
        issue.match_rules_json = None if configured else json.dumps({"version": 1, "all": [{"field": "related_tool", "op": "eq", "value": "start_report_export"}]})
        issue.agent_playbook_json = None if configured else json.dumps({"version": 1, "summary": "changed", "steps": [], "do_not_do": [], "recommended_tool_sequence": [], "safe_to_retry": False})
        await session.commit()

    await triage._restore_known_issue_config(
        SimpleNamespace(known_issue_id=issue_id, config_json=str(snapshot))
    )
    async with factory() as session:
        restored = await session.get(KnownIssue, issue_id)
        assert restored.title == "KI-45 before"
        assert restored.error_fingerprint_hash == "old-hash"
        assert (json.loads(restored.match_rules_json) if restored.match_rules_json else None) == original_rules
        assert (json.loads(restored.agent_playbook_json) if restored.agent_playbook_json else None) == original_playbook


def test_parser_exposes_stage332_commands():
    parser = triage._build_parser()
    move = parser.parse_args(["move-fingerprint", "45", "81", "--expected-fingerprint", "abc"])
    show = parser.parse_args(["show-known-issue-config", "45"])
    restore = parser.parse_args(["restore-known-issue-config", "45", "--config-json", "/tmp/x.json"])
    assert (move.source_id, move.target_id) == (45, 81)
    assert move.expected_fingerprint == "abc"
    assert show.known_issue_id == 45
    assert restore.config_json == "/tmp/x.json"

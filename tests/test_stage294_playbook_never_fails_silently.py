"""Этап 294 — playbook не должен молча выпадать из выдачи агенту.

18.06.2026 заведена известная проблема #11 с валидным playbook: она дословно
описывает предел выдачи Report AI и путь через экспорт. 01.09.2026 этап 276
переименовал `get_report_export_file` в `get_report_export_download`.
`validate_agent_playbook` отвергает playbook **целиком**, если хоть одно имя в
`recommended_tool_sequence` отсутствует в реестре инструментов, — и проблема
исчезла из выдачи. 03.09.2026 пришёл отчёт #62 ровно про то, что в ней описано.

Два дня знание существовало и не доходило. Ни одной записи в логе, ни одного
счётчика: в `unreachable-issues` «playbook отвергнут» выглядело так же, как
«playbook не написан», хотя чинятся они по-разному.

Тесты держат три вещи: отказ валидации называет причину, разбор различает два
состояния, и переименование инструмента ломает проверку, а не базу знаний.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_feedback_service as feedback
from tool_access_registry import TOOL_REQUIRED_SCOPES


def _playbook(*, tools: list[str]) -> str:
    return json.dumps(
        {
            "version": 1,
            "summary": "Large report data is capped; use the export path.",
            "steps": ["Call the export tool."],
            "do_not_do": ["Do not poll for more rows."],
            "recommended_tool_sequence": tools,
            "safe_to_retry": True,
        },
        ensure_ascii=False,
    )


def test_unknown_tool_name_is_reported_with_its_reason(caplog) -> None:
    """Точный случай #11: одно мёртвое имя гасит весь playbook."""
    raw = _playbook(tools=["get_report_ai_job_export", "get_report_export_file"])

    with caplog.at_level("WARNING"):
        result = feedback.validate_agent_playbook(raw)

    assert result is None
    events = [
        record for record in caplog.records
        if getattr(record, "event_name", "") == "agent_playbook_rejected"
    ]
    assert events, "playbook отвергнут молча — ровно так и потерялась проблема #11"
    assert getattr(events[0], "reason", "") == "unknown_tool"
    assert "get_report_export_file" in getattr(events[0], "detail", "")


def test_valid_playbook_logs_nothing() -> None:
    """Событие должно означать поломку, а не сопровождать обычную работу."""
    raw = _playbook(tools=["get_report_ai_job_export"])

    assert feedback.validate_agent_playbook(raw) is not None


@pytest.mark.parametrize(
    "raw, reason",
    [
        ("{not json", "malformed_json"),
        (json.dumps({"version": 2, "summary": "x"}), "unsupported_version"),
        (json.dumps({"version": 1}), "invalid_summary"),
    ],
)
def test_each_rejection_reason_is_named(raw: str, reason: str, caplog) -> None:
    """Причин отказа несколько, и «playbook не принят» без причины бесполезно."""
    with caplog.at_level("WARNING"):
        assert feedback.validate_agent_playbook(raw) is None

    events = [
        record for record in caplog.records
        if getattr(record, "event_name", "") == "agent_playbook_rejected"
    ]
    assert events and getattr(events[0], "reason", "") == reason


def test_absent_playbook_is_not_a_rejection(caplog) -> None:
    """У большинства проблем playbook просто не написан — это не поломка."""
    with caplog.at_level("WARNING"):
        assert feedback.validate_agent_playbook(None) is None
        assert feedback.validate_agent_playbook("") is None

    assert not [
        record for record in caplog.records
        if getattr(record, "event_name", "") == "agent_playbook_rejected"
    ]


def test_every_seeded_playbook_names_tools_that_exist() -> None:
    """Сторож на будущее: переименование инструмента ломает эту проверку.

    Именно её не хватало 01.09 — этап 276 переименовал инструмент, все тесты
    остались зелёными, а база знаний потеряла проблему уровня high.
    """
    import scripts.seed_known_issues as seed

    for issue in seed.SEED_ISSUES:
        for tool in issue.agent_playbook.get("recommended_tool_sequence", []):
            assert tool in TOOL_REQUIRED_SCOPES, (
                f"[seed:{issue.slug}] ссылается на несуществующий инструмент {tool!r}"
            )
        if issue.related_tool:
            assert issue.related_tool in TOOL_REQUIRED_SCOPES, (
                f"[seed:{issue.slug}] related_tool {issue.related_tool!r} не существует"
            )


@pytest.mark.asyncio
async def test_triage_separates_rejected_playbook_from_absent_one(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """Разбор должен показывать разные состояния по-разному.

    «Написать playbook» и «починить имя инструмента в playbook» — разная
    работа, а в отчёте они выглядели одинаково.
    """
    import scripts.triage_agent_feedback as triage
    from storage_models import KnownIssue

    session_factory = await sqlite_session_factory_builder(tmp_path / "unreachable.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)

    async with session_factory() as session:
        session.add_all([
            KnownIssue(
                status="acknowledged", category="bug", severity="high",
                title="playbook со сломанным именем инструмента",
                related_tool="get_report_ai_job_data",
                agent_playbook_json=_playbook(tools=["get_report_export_file"]),
            ),
            KnownIssue(
                status="acknowledged", category="bug", severity="medium",
                title="playbook не написан вовсе",
                related_tool="get_pets",
            ),
        ])
        await session.commit()

    await triage._unreachable_issues(type("Args", (), {})())
    out = capsys.readouterr().out

    assert "playbook_state" in out, "разбор не различает два состояния"
    assert "rejected" in out
    assert "missing" in out


@pytest.mark.asyncio
async def test_set_playbook_repairs_an_issue_the_agent_stopped_hearing(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """294.4: починить существующий playbook было нечем.

    04.09.2026 замена одного устаревшего имени инструмента в playbook #11
    потребовала разового скрипта внутри боевого контейнера, потому что
    `promote` заводит новую проблему, а `mark` меняет только статус.
    """
    import scripts.triage_agent_feedback as triage
    from storage_models import KnownIssue

    session_factory = await sqlite_session_factory_builder(tmp_path / "set-playbook.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)

    async with session_factory() as session:
        issue = KnownIssue(
            status="workaround_available", category="bug", severity="high",
            title="ответ есть, но имя инструмента устарело",
            related_tool="get_report_ai_job_data",
            agent_playbook_json=_playbook(tools=["get_report_export_file"]),
        )
        session.add(issue)
        await session.commit()
        await session.refresh(issue)
        issue_id = issue.id

    repaired = tmp_path / "repaired.json"
    repaired.write_text(_playbook(tools=["get_report_export_download"]), encoding="utf-8")

    await triage._set_playbook(
        type("Args", (), {"known_issue_id": issue_id, "playbook_json": str(repaired)})()
    )
    out = capsys.readouterr().out

    assert "was_reachable=False now_reachable=True" in out
    async with session_factory() as session:
        stored = await session.get(KnownIssue, issue_id)
        assert feedback.validate_agent_playbook(stored.agent_playbook_json) is not None


@pytest.mark.asyncio
async def test_set_playbook_refuses_to_overwrite_with_an_invalid_one(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Плохой playbook не должен заменить рабочий — валидация та же, что на записи."""
    import scripts.triage_agent_feedback as triage
    from storage_models import KnownIssue

    session_factory = await sqlite_session_factory_builder(tmp_path / "refuse.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)
    good = _playbook(tools=["get_report_ai_job_export"])

    async with session_factory() as session:
        issue = KnownIssue(
            status="acknowledged", category="bug", severity="medium",
            title="рабочий playbook", related_tool="get_pets",
            agent_playbook_json=good,
        )
        session.add(issue)
        await session.commit()
        await session.refresh(issue)
        issue_id = issue.id

    broken = tmp_path / "broken.json"
    broken.write_text(_playbook(tools=["tool_that_does_not_exist"]), encoding="utf-8")

    with pytest.raises(SystemExit):
        await triage._set_playbook(
            type("Args", (), {"known_issue_id": issue_id, "playbook_json": str(broken)})()
        )

    async with session_factory() as session:
        stored = await session.get(KnownIssue, issue_id)
        assert stored.agent_playbook_json == good

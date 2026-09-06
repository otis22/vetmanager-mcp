"""Этап 305.3–305.4: правила можно починить, и разбор не обещает лишнего.

Две дыры, найденные при разборе снимка правил с прода 06.09.2026.

Первая: правила существующей проблемы нечем изменить. `promote` задаёт их при
создании, `set-playbook` правит только playbook. Ровно та дыра, которую этап
294.4 закрыл для playbook — для правил она осталась открытой, и одиннадцать
живущих на проде правил менялись бы разовым скриптом внутри боевого контейнера.

Вторая: `{"version": 1, "all": []}` проходит валидацию и совпадает с любым
инцидентом. Пока правила заводились только при создании проблемы, это было
теоретической дырой; команда правки делает её достижимой одним неверным файлом.

Была и третья, заявленная в первой редакции PRD: будто колонка `injection` в
разборе обещает доставку у проблемы в закрытом статусе. Проверка на проде
07.09.2026 посылку не подтвердила — `unreachable-issues` отбирает строки по
`KB_AGENT_STATUSES`, и проблема в `wontfix` в отчёт не попадает вовсе. Правка
была бы мёртвым кодом; пункт закрыт как неверная посылка, а не сделан.
"""

from __future__ import annotations

import json

import pytest

from agent_feedback_service import validate_match_rules_json
import scripts.triage_agent_feedback as triage
from storage_models import KnownIssue

VALID_RULES = {
    "version": 1,
    "all": [{"field": "related_tool", "op": "eq", "value": "get_pets"}],
}
VALID_PLAYBOOK = {
    "version": 1,
    "summary": "Read pets through the owner card.",
    "steps": ["Open the owner card and read the pets from it."],
    "do_not_do": ["Do not retry the same list call."],
    "recommended_tool_sequence": ["get_client_by_id"],
    "safe_to_retry": False,
}


def test_an_empty_condition_list_is_no_longer_a_valid_rule() -> None:
    """Правило без условий совпадает со всем — и молча затеняет остальные.

    У проблемы с `related_tool = None` такая запись становится кандидатом почти
    на каждый отказ, а выбирается первый по `priority`.
    """
    assert validate_match_rules_json(json.dumps({"version": 1, "all": []})) is None


def test_a_rule_with_conditions_stays_valid() -> None:
    assert validate_match_rules_json(json.dumps(VALID_RULES)) is not None


@pytest.mark.asyncio
async def test_rules_of_an_existing_issue_can_be_replaced(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "rules.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)

    async with session_factory() as session:
        issue = KnownIssue(
            status="acknowledged", category="bug", severity="medium",
            title="Правило устарело", related_tool="get_pets",
            match_rules_json=json.dumps({
                "version": 1,
                "all": [{"field": "related_tool", "op": "eq", "value": "get_pets_old"}],
            }),
            agent_playbook_json=json.dumps(VALID_PLAYBOOK),
        )
        session.add(issue)
        await session.commit()
        issue_id = issue.id

    path = tmp_path / "rules.json"
    path.write_text(json.dumps(VALID_RULES), encoding="utf-8")

    await triage._set_match_rules(
        type("Args", (), {"known_issue_id": issue_id, "match_rules_json": str(path)})()
    )

    async with session_factory() as session:
        stored = await session.get(KnownIssue, issue_id)
        assert json.loads(stored.match_rules_json)["all"][0]["value"] == "get_pets"

    assert "match rules updated" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_invalid_rules_do_not_replace_working_ones(
    sqlite_session_factory_builder, tmp_path, monkeypatch
) -> None:
    """Отказ должен быть отказом: рабочее правило переживает неверный файл."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "rules_bad.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)

    working = json.dumps(VALID_RULES)
    async with session_factory() as session:
        issue = KnownIssue(
            status="acknowledged", category="bug", severity="medium",
            title="Рабочее правило", related_tool="get_pets",
            match_rules_json=working,
            agent_playbook_json=json.dumps(VALID_PLAYBOOK),
        )
        session.add(issue)
        await session.commit()
        issue_id = issue.id

    for payload in ({"version": 1, "all": []}, {"version": 2, "all": [{"field": "x"}]}):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(SystemExit):
            await triage._set_match_rules(
                type("Args", (), {"known_issue_id": issue_id, "match_rules_json": str(path)})()
            )

    async with session_factory() as session:
        stored = await session.get(KnownIssue, issue_id)
    assert stored.match_rules_json == working

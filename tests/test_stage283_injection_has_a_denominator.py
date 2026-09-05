"""Этап 283.1 — у «инжекция сработала 0 раз» появился знаменатель.

За всю историю продукта в `known_issue_match_events` одна строка, и та по
ручному пути. Ноль сам по себе не читается: это либо «отказов инструментов не
было», либо «их были тысячи и не совпал ни один». В Sentry такие отказы не
летят — они обработаны, — поэтому счёт ведётся своей метрикой.

Считается каждая попытка поиска известной проблемы по живому отказу, с исходом:
`matched`, `no_match`, `lookup_failed`. Последний важен отдельно: поиск ограничен
таймаутом, и «не нашли» не должно выглядеть так же, как «не успели посмотреть».
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

import agent_feedback_service as feedback
from service_metrics import (
    KNOWN_ISSUE_LOOKUP_OUTCOMES,
    record_known_issue_lookup,
    reset_service_metrics,
    snapshot_service_metrics,
)
from tests.runtime_factories import make_runtime_credentials


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_service_metrics()
    yield
    reset_service_metrics()


def _counts() -> dict[str, int]:
    return snapshot_service_metrics()["known_issue_lookups_total"]


def test_outcomes_are_a_closed_set() -> None:
    assert KNOWN_ISSUE_LOOKUP_OUTCOMES == ("matched", "no_match", "lookup_failed")


def test_unknown_outcome_is_dropped_not_counted() -> None:
    """Метрика с опечаткой в исходе хуже отсутствующей: она выглядит цифрой."""
    record_known_issue_lookup(tool_name="get_clients", outcome="probably")

    assert _counts() == {}


def test_each_outcome_is_counted_per_tool() -> None:
    record_known_issue_lookup(tool_name="get_clients", outcome="no_match")
    record_known_issue_lookup(tool_name="get_clients", outcome="no_match")
    record_known_issue_lookup(tool_name="get_invoices", outcome="matched")

    assert _counts() == {"get_clients|no_match": 2, "get_invoices|matched": 1}


def test_tool_label_is_sanitised() -> None:
    """Метка идёт в Prometheus: посторонние символы ломают кардинальность."""
    record_known_issue_lookup(tool_name="get clients/../etc", outcome="no_match")

    assert list(_counts()) == ["get_clients_.._etc|no_match"]


def test_counter_reaches_prometheus_output() -> None:
    from service_metrics import render_prometheus_metrics

    record_known_issue_lookup(tool_name="get_invoices", outcome="no_match")
    rendered = render_prometheus_metrics()

    assert "vetmanager_known_issue_lookups_total" in rendered
    assert 'outcome="no_match"' in rendered


@pytest.mark.asyncio
async def test_a_tool_failure_without_a_match_is_counted_as_no_match(monkeypatch) -> None:
    """Главный случай: отказ был, совпадения не нашлось — и это видно."""
    async def _no_match(_tool_name, _exc):
        return None

    monkeypatch.setattr(feedback, "lookup_known_issue_for_error", _no_match)
    monkeypatch.setattr(feedback, "write_auto_feedback_event", _noop)

    await feedback.augment_tool_error(
        "get_invoices", make_runtime_credentials("clinic", "secret"), ToolError("upstream refused")
    )

    assert _counts().get("get_invoices|no_match") == 1


async def _noop(*_args, **_kwargs) -> None:
    return None


@pytest.mark.asyncio
async def test_a_failed_lookup_is_not_confused_with_no_match(monkeypatch) -> None:
    """Поиск ограничен таймаутом: «не успели» и «не нашли» — разные факты."""
    async def _boom(_tool_name, _exc):
        raise RuntimeError("db is away")

    monkeypatch.setattr(feedback, "lookup_known_issue_for_error", _boom)
    monkeypatch.setattr(feedback, "write_auto_feedback_event", _noop)

    await feedback.augment_tool_error(
        "get_pets", make_runtime_credentials("clinic", "secret"), ToolError("upstream refused")
    )

    counts = _counts()
    assert counts.get("get_pets|lookup_failed") == 1
    assert "get_pets|no_match" not in counts


# --- Этап 283.2 — «найдётся при разборе» и «дойдёт до агента» разные вещи ----


@pytest.mark.asyncio
async def test_triage_separates_manual_reach_from_injection_reach(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    """Отпечаток проблемы приходит из отчёта, а инжекция считает свой — из
    живого исключения. Они не совпадают по построению, поэтому при отказе
    инструмента проблему находит только написанное человеком правило.

    До этого `matchable=yes` читалось как «дойдёт до агента», хотя означало
    «найдётся, когда человек будет разбирать».
    """
    import scripts.triage_agent_feedback as triage
    from storage_models import KnownIssue

    session_factory = await sqlite_session_factory_builder(tmp_path / "injection.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)

    async with session_factory() as session:
        session.add_all([
            KnownIssue(
                status="acknowledged", category="bug", severity="high",
                title="только отпечаток из отчёта", related_tool="get_invoices",
                error_fingerprint_hash="hmac-sha256:deadbeef",
            ),
            KnownIssue(
                status="acknowledged", category="bug", severity="medium",
                title="есть правило", related_tool="get_pets",
                match_rules_json='{"version": 1, "all": [{"field": "related_tool", "op": "eq", "value": "get_pets"}]}',
            ),
        ])
        await session.commit()

    await triage._unreachable_issues(type("Args", (), {})())
    out = capsys.readouterr().out

    assert "injection" in out

    def _cells(needle: str) -> list[str]:
        line = next(l for l in out.splitlines() if needle in l and l.startswith("|"))
        return [c.strip() for c in line.strip("|").split("|")]

    header = _cells("| id |")
    matchable_at = header.index("matchable")
    injection_at = header.index("injection")

    only_fingerprint = _cells("get_invoices")
    with_rules = _cells("get_pets")

    # Найдутся при ручном разборе оба; дойдёт до агента при отказе — только
    # тот, у кого есть написанное человеком правило.
    assert only_fingerprint[matchable_at] == "yes"
    assert only_fingerprint[injection_at] == "no"
    assert with_rules[matchable_at] == "yes"
    assert with_rules[injection_at] == "yes"

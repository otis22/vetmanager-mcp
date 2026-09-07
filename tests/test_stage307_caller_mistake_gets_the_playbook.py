"""Этап 307: ошибке вызывающего playbook полезнее всего — и её же он не видит.

Этап 265.5 закрыл настоящую проблему: механизм обвинял продукт в чужой
опечатке. Но `should_skip_report_hint` выключил разом три вещи — приглашение
сообщить о дефекте, авто-отчёт о дефекте и доставку разобранного playbook.
Первые две выключены верно. Третья — побочный эффект: playbook не обвиняет, он
говорит, что сделать вместо.

Цена видна на живых классах (Sentry, 90 дней): `INVALID_TRANSITION` при
сохранении отчёта Report AI — 4 события, `Report is not REST-exportable` — 2.
Оба стали `ToolInputError` уже после того, как события записались, и потому в
корпусе этапа 305 лежали в разделе «недостижимо по замыслу».

Проверка идёт через настоящую обёртку: вызов `augment_tool_error` напрямую был
бы зелёным и сегодня, потому что дефект живёт не в ней, а в ветке, которая до
неё не доходит.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

import agent_feedback_service as feedback
import tools
from exceptions import ToolInputError
from storage_models import AgentFeedbackReport, KnownIssue, KnownIssueMatchEvent
from tests.runtime_factories import make_runtime_credentials
from tool_error_tracking import ToolErrorTrackingMiddleware

HINT = "call report_problem"

# Playbook по-английски намеренно: `augment_tool_error` сериализует его с
# `ensure_ascii=True`, и кириллица доехала бы до агента экранированной.
PLAYBOOK = json.dumps({
    "version": 1,
    "summary": "The job still waits for the candidate to be confirmed.",
    "steps": [
        "Call confirm_report_ai_job_candidate for this job first.",
        "Save the report only after the job leaves needs_confirmation.",
    ],
    "do_not_do": ["Do not retry the save — the status will not change by itself."],
    "recommended_tool_sequence": ["confirm_report_ai_job_candidate"],
    "safe_to_retry": False,
})

INVALID_TRANSITION = (
    "Upstream API error (HTTP 409): INVALID_TRANSITION — "
    "save is not available from status 'needs_confirmation'"
)


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "test-feedback-pepper")


@pytest.fixture
async def wrap_failing_tool(sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper):
    """Падающий инструмент за настоящей обёрткой, с живой базой известных проблем."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage307.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret")
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    def _wrap(exc: BaseException, *, tool_name: str = "save_report_ai_job_as_report"):
        async def failing_tool():
            raise exc

        return tools._wrap_tool_with_depersonalization(failing_tool, tool_name=tool_name)

    _wrap.session_factory = session_factory
    return _wrap


async def _seed_issue(session_factory, *, marker: str = "invalid_transition") -> None:
    rules = json.dumps({
        "version": 1,
        "all": [{"field": "normalized_error_text", "op": "contains_any", "value": [marker]}],
    })
    async with session_factory() as session:
        session.add(KnownIssue(
            status="workaround_available", category="contract", severity="medium",
            title="Сохранение отчёта до подтверждения кандидата", related_tool=None,
            match_rules_json=rules, agent_playbook_json=PLAYBOOK,
        ))
        await session.commit()


# --- 307.1: playbook доезжает, обвинение — нет ------------------------------


@pytest.mark.asyncio
async def test_a_caller_mistake_now_receives_the_playbook(wrap_failing_tool) -> None:
    """Сторож принимается красным: сегодня ветка уходит ранним `raise`."""
    await _seed_issue(wrap_failing_tool.session_factory)
    wrapped = wrap_failing_tool(ToolInputError(INVALID_TRANSITION))

    with pytest.raises(ToolInputError) as raised:
        await wrapped()

    answer = str(raised.value)
    assert "Known issue playbook" in answer
    assert "confirm_report_ai_job_candidate" in answer


@pytest.mark.asyncio
async def test_the_playbook_arrives_without_an_invitation_to_blame_the_product(
    wrap_failing_tool,
) -> None:
    """Этап 265.5 остаётся в силе: подписи в ответе быть не должно."""
    await _seed_issue(wrap_failing_tool.session_factory)
    wrapped = wrap_failing_tool(ToolInputError(INVALID_TRANSITION))

    with pytest.raises(ToolInputError) as raised:
        await wrapped()

    assert HINT not in str(raised.value)


@pytest.mark.asyncio
async def test_a_caller_mistake_does_not_write_a_defect_report(wrap_failing_tool) -> None:
    """Авто-отчёт утверждает, что виноват продукт, — для опечатки это ложь.

    Заодно это ровно половина цены журнала: у потока отказов одно совпадение
    стоит две строки (`injection` и `auto`), здесь остаётся одна.
    """
    await _seed_issue(wrap_failing_tool.session_factory)
    wrapped = wrap_failing_tool(ToolInputError(INVALID_TRANSITION))

    with pytest.raises(ToolInputError):
        await wrapped()

    async with wrap_failing_tool.session_factory() as session:
        events = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
        reports = (await session.execute(select(AgentFeedbackReport))).scalars().all()

    assert [event.source for event in events] == ["injection"]
    assert reports == []


@pytest.mark.asyncio
async def test_an_augmented_caller_mistake_still_stays_out_of_sentry(wrap_failing_tool) -> None:
    """Ловушка, найденная при разборе кода этапа 307.

    `augment_tool_error` строит плоский `ToolError`. Если пропустить через него
    ошибку вызывающего наивно, она перестанет быть `ToolInputError` — и
    `tool_error_tracking.py` заведёт на неё issue как на дефект продукта,
    отменив этап 265.6. Проверяется на том, что реально вышло из обёртки.
    """
    await _seed_issue(wrap_failing_tool.session_factory)
    wrapped = wrap_failing_tool(ToolInputError(INVALID_TRANSITION))

    with pytest.raises(ToolInputError) as raised:
        await wrapped()

    augmented = raised.value
    middleware = ToolErrorTrackingMiddleware()

    async def fail(_context):
        raise augmented

    with patch("tool_error_tracking.capture_tool_failure") as capture:
        with pytest.raises(ToolInputError):
            await middleware.on_call_tool(
                SimpleNamespace(message=SimpleNamespace(name="save_report_ai_job_as_report")), fail,
            )

    capture.assert_not_called()


@pytest.mark.asyncio
async def test_a_caller_mistake_without_a_known_issue_comes_back_untouched(
    wrap_failing_tool,
) -> None:
    """Нет правила — нет и хвостов: агент видит ровно то, что видел раньше."""
    wrapped = wrap_failing_tool(ToolInputError("clinic_id must be a positive integer."))

    with pytest.raises(ToolInputError) as raised:
        await wrapped()

    assert str(raised.value) == "clinic_id must be a positive integer."


@pytest.mark.asyncio
async def test_an_unavailable_database_does_not_start_blaming_the_caller(
    wrap_failing_tool, monkeypatch,
) -> None:
    """Ветка `lookup_failed` — отдельный ранний возврат, и флаг обязан жить в ней.

    Найдено ревью PRD: реализация могла бы поставить условие только на
    счастливый путь, и при недоступной базе опечатка снова получала бы
    приглашение сообщить о дефекте.
    """
    async def explode(*args, **kwargs):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(feedback, "lookup_known_issue_for_error", explode)
    wrapped = wrap_failing_tool(ToolInputError(INVALID_TRANSITION))

    with pytest.raises(ToolInputError) as raised:
        await wrapped()

    assert HINT not in str(raised.value)
    assert "Known issue playbook" not in str(raised.value)


@pytest.mark.asyncio
async def test_a_subclass_carrying_its_own_state_still_bypasses_augmentation(
    wrap_failing_tool,
) -> None:
    """Граница проведена по точному типу, а не по `isinstance`.

    Произвольный подкласс пересобрать нельзя — у него своя сигнатура
    `__init__`, и augmentation вернула бы другой объект, потеряв его атрибуты.
    Тот же приём уже применён рядом: редактирование приватности работает по
    `type(exc) is ToolError`.
    """
    class SpecializedInputError(ToolInputError):
        def __init__(self, message, marker):
            super().__init__(message)
            self.marker = marker

    await _seed_issue(wrap_failing_tool.session_factory)
    original = SpecializedInputError(INVALID_TRANSITION, marker="keep")
    wrapped = wrap_failing_tool(original)

    with pytest.raises(SpecializedInputError) as raised:
        await wrapped()

    assert raised.value is original
    assert raised.value.marker == "keep"


# --- 307.1: знаменатель не смешивает два потока -----------------------------


@pytest.mark.asyncio
async def test_the_counter_keeps_the_two_streams_apart(wrap_failing_tool) -> None:
    """Этап 306 считал поток отказов. Ошибки аргументов — другой поток.

    Сложить их в один счётчик значит повторить ошибку этапа 283: метрика
    останется зелёной и будет отвечать не на тот вопрос, который задан.
    """
    from service_metrics import reset_service_metrics, snapshot_service_metrics
    from exceptions import VetmanagerError

    reset_service_metrics()
    with pytest.raises(ToolInputError):
        await wrap_failing_tool(ToolInputError("clinic_id must be a positive integer."))()
    with pytest.raises(ToolError):
        await wrap_failing_tool(VetmanagerError("Upstream API error (HTTP 500) — boom"))()

    counts = snapshot_service_metrics()["known_issue_lookups_total"]

    assert counts.get("save_report_ai_job_as_report|no_match|caller_mistake") == 1
    assert counts.get("save_report_ai_job_as_report|no_match|failure") == 1


def test_the_counter_renders_the_new_label_for_prometheus() -> None:
    """Метка бесполезна, если не доезжает до Prometheus."""
    from service_metrics import (
        record_known_issue_lookup,
        render_prometheus_metrics,
        reset_service_metrics,
    )

    reset_service_metrics()
    record_known_issue_lookup(tool_name="get_pets", outcome="matched", kind="caller_mistake")

    rendered = render_prometheus_metrics()

    assert (
        'vetmanager_known_issue_lookups_total'
        '{tool="get_pets",outcome="matched",kind="caller_mistake"} 1'
    ) in rendered


def test_an_unknown_kind_is_dropped_like_an_unknown_outcome() -> None:
    """Метка кардинальности принимает только известные значения."""
    from service_metrics import (
        record_known_issue_lookup,
        reset_service_metrics,
        snapshot_service_metrics,
    )

    reset_service_metrics()
    record_known_issue_lookup(tool_name="get_pets", outcome="matched", kind="whatever")

    assert snapshot_service_metrics()["known_issue_lookups_total"] == {}

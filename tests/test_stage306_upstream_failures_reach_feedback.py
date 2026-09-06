"""Этап 306: отказ апстрима должен доходить до механизма обратной связи.

Замер 06.09.2026 по Sentry за 90 дней: из 6 096 событий до `augment_tool_error`
дошло 11 — 0.2%. Признак доставки взят из самого события: подпись
`call report_problem` дописывает только `augment_tool_error`.

Причина: обёртка ловит `except ToolError`, а инструменты в массе бросают
`VetmanagerError` и наследников. В `ToolError` их превращает FastMCP уровнем
выше, уже после обёртки, — поэтому в Sentry виден `ToolError`, и по этому
верхнему типу отказы годами считались достижимыми.

Граница перехвата не «всё, что упало». Три класса остаются за ней, и каждый
потому, что не является дефектом продукта: `NotFoundError` (404 от
`get_*_by_id` — обычный устаревший идентификатор), `AuthError` (отказ доступа),
`RateLimitError` (наш собственный ограничитель частоты, апстрим его не бросает
вовсе). Приглашать сообщить о них как о баге значит учить агента заводить баги
на нормальную работу системы.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

import agent_feedback_service as feedback
import tools
from exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
    ToolInputError,
    VetmanagerError,
    VetmanagerTimeoutError,
    VetmanagerUpstreamUnavailable,
)
from filters import FilterPropertyValidationError, SortPropertyValidationError
from storage_models import KnownIssueMatchEvent
from tests.runtime_factories import make_runtime_credentials

HINT = "call report_problem"


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "test-feedback-pepper")


@pytest.fixture
async def wrap_failing_tool(sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper):
    """Инструмент, падающий заданным исключением, за настоящей обёрткой.

    Проверять здесь `augment_tool_error` напрямую бессмысленно: он и сегодня
    принимает любое исключение, и такой тест был бы зелёным без единой правки
    в том месте, где живёт дефект.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage306.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret")
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    def _wrap(exc: BaseException, *, tool_name: str = "get_invoice_by_id"):
        async def failing_tool():
            raise exc

        return tools._wrap_tool_with_depersonalization(failing_tool, tool_name=tool_name)

    _wrap.session_factory = session_factory
    return _wrap


# --- то, что должно доходить ------------------------------------------------


@pytest.mark.parametrize(
    "exc, events",
    [
        (VetmanagerUpstreamUnavailable("VM API circuit breaker half-open for alternativa"), 5336),
        (VetmanagerTimeoutError("Timeout requesting Vetmanager upstream. Please retry shortly."), 657),
        (VetmanagerError("Upstream API error (HTTP 500) — No Clinic selected"), 20),
    ],
    ids=["circuit-breaker", "upstream-timeout", "plain-upstream-error"],
)
@pytest.mark.asyncio
async def test_upstream_failure_reaches_the_feedback_path(wrap_failing_tool, exc, events) -> None:
    """Самый частый отказ на бою обязан пройти тем же путём, что наш ToolError."""
    wrapped = wrap_failing_tool(exc)

    with pytest.raises(ToolError) as raised:
        await wrapped()

    assert HINT in str(raised.value), f"{events} событий за 90 дней проходят мимо механизма"
    assert raised.value.__cause__ is exc


@pytest.mark.parametrize(
    "exc",
    [
        FilterPropertyValidationError("Unknown filter property 'close_date'. Allowed properties: date, id"),
        SortPropertyValidationError("Unknown sort property 'close_date'. Allowed properties: date, id"),
    ],
    ids=["filter-contract", "sort-contract"],
)
@pytest.mark.asyncio
async def test_local_contract_failure_reaches_the_feedback_path(wrap_failing_tool, exc) -> None:
    """Наш собственный отказ по контракту — тоже повод показать известную проблему.

    Ловятся именно эти два класса, а не `ValueError` целиком: перехват всего
    `ValueError` затянул бы в путь обратной связи случайные ошибки кода, где
    подпись «сообщите о проблеме» уводит от настоящей причины.
    """
    wrapped = wrap_failing_tool(exc, tool_name="get_cassa_closes")

    with pytest.raises(ToolError) as raised:
        await wrapped()

    assert HINT in str(raised.value)


@pytest.mark.asyncio
async def test_a_random_value_error_is_not_dragged_into_the_feedback_path(wrap_failing_tool) -> None:
    """Граница проверяется с другой стороны: обычный ValueError остаётся собой."""
    boom = ValueError("int() argument must be a string")
    wrapped = wrap_failing_tool(boom)

    with pytest.raises(ValueError) as raised:
        await wrapped()

    assert raised.value is boom


# --- то, что доходить не должно ---------------------------------------------


@pytest.mark.asyncio
async def test_record_not_found_is_not_a_defect(wrap_failing_tool) -> None:
    """404 от `get_*_by_id` — устаревший идентификатор, а не баг продукта."""
    wrapped = wrap_failing_tool(NotFoundError("Resource not found", status_code=404))

    with pytest.raises(NotFoundError) as raised:
        await wrapped()

    assert HINT not in str(raised.value)


@pytest.mark.asyncio
async def test_access_denial_is_not_a_defect(wrap_failing_tool) -> None:
    wrapped = wrap_failing_tool(AuthError("Invalid API key"))

    with pytest.raises(AuthError) as raised:
        await wrapped()

    assert HINT not in str(raised.value)


@pytest.mark.asyncio
async def test_our_own_rate_limit_is_not_a_defect_and_keeps_its_retry_hint(wrap_failing_tool) -> None:
    """Апстрим `RateLimitError` не бросает вовсе — это наш ограничитель частоты.

    Вместе с подписью он потерял бы и `retry_after_seconds`, по которому
    вызывающий понимает, когда повторить.
    """
    wrapped = wrap_failing_tool(RateLimitError("Too many requests", retry_after_seconds=17))

    with pytest.raises(RateLimitError) as raised:
        await wrapped()

    assert HINT not in str(raised.value)
    assert raised.value.retry_after_seconds == 17


@pytest.mark.asyncio
async def test_caller_mistake_still_passes_without_a_hint(wrap_failing_tool) -> None:
    """Этап 265.5 не сломан расширением перехвата."""
    wrapped = wrap_failing_tool(ToolInputError("Invalid date_from format."))

    with pytest.raises(ToolInputError) as raised:
        await wrapped()

    assert HINT not in str(raised.value)


# --- побочные следствия расширения ------------------------------------------


@pytest.mark.asyncio
async def test_upstream_text_now_goes_through_privacy_redaction(wrap_failing_tool) -> None:
    """Сегодня текст апстрима уходит к клиенту мимо редактирования.

    `redact_tool_error` работает по точному типу `ToolError`
    (`type(exc) is ToolError`), а `VetmanagerError` под него не попадал вовсе.
    """
    payload = json.dumps({"passwd": "hunter2", "id": 7})
    wrapped = wrap_failing_tool(VetmanagerError(payload))

    with pytest.raises(ToolError) as raised:
        await wrapped()

    assert "hunter2" not in str(raised.value)
    assert "passwd" not in str(raised.value)


@pytest.mark.asyncio
async def test_a_flood_of_upstream_failures_writes_nothing_without_rules(wrap_failing_tool) -> None:
    """Расширение перехвата само по себе не наливает строк в журнал совпадений.

    Событие, авто-отчёт и инкремент `report_count` начинаются только после
    найденной известной проблемы. Правил под эти классы пока нет — значит и
    записей быть не должно, сколько бы отказов ни прошло.
    """
    wrapped = wrap_failing_tool(VetmanagerUpstreamUnavailable("circuit breaker open for alternativa"))

    for _ in range(25):
        with pytest.raises(ToolError):
            await wrapped()

    async with wrap_failing_tool.session_factory() as session:
        events = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()

    assert events == []


@pytest.mark.asyncio
async def test_the_lookup_counter_now_sees_the_real_stream(wrap_failing_tool) -> None:
    """Знаменатель этапа 283.1 впервые считает настоящий поток отказов."""
    from service_metrics import snapshot_service_metrics

    wrapped = wrap_failing_tool(VetmanagerUpstreamUnavailable("circuit breaker open for alternativa"))

    with pytest.raises(ToolError):
        await wrapped()

    counts = snapshot_service_metrics()["known_issue_lookups_total"]
    assert counts.get("get_invoice_by_id|no_match") == 1

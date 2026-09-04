"""Этап 295 — отпечаток без признака ошибки не привязывает отчёт к проблеме.

Отчёт #62 (03.09.2026) про обрыв выгрузки Report AI на 1000 строк автоматически
привязался к известной проблеме #42 про идентификаторы вместо имён врачей. Это
разные дефекты. Отпечаток считается по инструменту, HTTP-статусу, коду ошибки,
нормализованному тексту ошибки и форме параметров; у отчёта про **успешный**
вызов с неверными данными первых четырёх нет, и хеш схлопывается до
`get_report_ai_job_data` + `["job_id"]`.

Вред не остаётся внутри базы: `create_feedback_report` возвращает найденную
проблему вместе с playbook, то есть агент получил в ответ инструкцию про
подстановку имён врачей.

Тесты проверяют поведение на границе признака ошибки, а не наличие функции:
реализацию можно написать иначе, но инцидент без ошибки не должен матчиться,
а инцидент с ошибкой — должен, как и раньше.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

import agent_feedback_service as feedback
from storage_models import AgentFeedbackReport, KnownIssue
from tests.runtime_factories import make_runtime_credentials


PLAYBOOK_JSON = (
    '{"version": 1, "summary": "Wrong issue for this report.",'
    ' "steps": ["Do the wrong thing."], "do_not_do": [],'
    ' "recommended_tool_sequence": ["get_users"], "safe_to_retry": true}'
)

# Форма отчёта #62: успешный вызов, данные неверные. Ни статуса, ни кода,
# ни текста ошибки — только инструмент и форма параметров.
WRONG_RESULT_INCIDENT = dict(
    related_tool="get_report_ai_job_data",
    params_shape=["job_id"],
)


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage295-test-pepper")


async def _issue_with_fingerprint_of(
    session_factory,
    incident: feedback.FeedbackIncident,
    *,
    match_rules_json: str | None = None,
) -> int:
    """Известная проблема с тем же отпечатком, что у инцидента.

    Ровно так и появилась #42: `promote` копирует отпечаток отчёта, из которого
    проблема заведена.
    """
    async with session_factory() as session:
        issue = KnownIssue(
            status="acknowledged",
            category="bug",
            severity="medium",
            title="Другой дефект того же инструмента",
            related_tool=incident.related_tool,
            error_fingerprint_hash=feedback.build_error_fingerprint_hash(incident),
            agent_playbook_json=PLAYBOOK_JSON,
            match_rules_json=match_rules_json,
        )
        session.add(issue)
        await session.commit()
        await session.refresh(issue)
        return issue.id


@pytest.mark.asyncio
async def test_incident_without_error_signal_does_not_match_by_fingerprint(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Главный случай: отчёт #62 не должен получить playbook проблемы #42."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "no-signal.db")
    incident = feedback.FeedbackIncident(**WRONG_RESULT_INCIDENT)
    await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is None, (
        "инцидент без признака ошибки привязался по отпечатку, "
        "который у всех таких инцидентов одинаковый"
    )


@pytest.mark.asyncio
async def test_incident_with_error_text_still_matches_by_fingerprint(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Основной путь не трогаем: у отказа инструмента отпечаток осмысленный."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "error-text.db")
    incident = feedback.FeedbackIncident(
        related_tool="get_report_ai_job_data",
        error_code="ToolError",
        error_excerpt="Upstream refused the export with a specific message",
        params_shape=["job_id"],
    )
    issue_id = await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is not None
    assert match.id == issue_id


@pytest.mark.asyncio
async def test_http_status_alone_counts_as_error_signal(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Граница: `http_status=0` — обрыв соединения, а не отсутствие статуса.

    Этап 153 (F14) специально сохранил нулевой статус как признак; проверка на
    истинность вместо `is not None` тихо выключила бы матч для таких инцидентов.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "status-zero.db")
    incident = feedback.FeedbackIncident(
        related_tool="get_clients",
        http_status=0,
        params_shape=["limit"],
    )
    issue_id = await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is not None
    assert match.id == issue_id


@pytest.mark.asyncio
async def test_blank_error_code_is_not_an_error_signal(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Пустая строка в коде ошибки приходит с формы и ошибкой не является."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "blank-code.db")
    incident = feedback.FeedbackIncident(
        related_tool="get_report_ai_job_data",
        error_code="   ",
        error_excerpt="",
        params_shape=["job_id"],
    )
    await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is None


@pytest.mark.asyncio
async def test_human_written_rules_still_match_without_error_signal(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Запрет касается отпечатка, а не правил.

    Правила `match_rules_json` пишет человек и отвечает за них; это остаётся
    способом дотянуться до отчёта про неверные данные.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "rules.db")
    incident = feedback.FeedbackIncident(**WRONG_RESULT_INCIDENT)
    rules = (
        '{"version": 1, "all": ['
        '{"field": "related_tool", "op": "eq", "value": "get_report_ai_job_data"},'
        '{"field": "params_shape", "op": "has_keys", "value": ["job_id"]}'
        ']}'
    )
    issue_id = await _issue_with_fingerprint_of(
        session_factory, incident, match_rules_json=rules
    )

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is not None
    assert match.id == issue_id


@pytest.mark.asyncio
async def test_auto_event_lookup_obeys_the_same_boundary(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Второй вход в тот же перебор кандидатов — событие сопоставления.

    Если запрет поставить только в `find_known_issue_match`, автоматические
    события продолжат записывать чужую проблему.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "auto-event.db")
    incident = feedback.FeedbackIncident(**WRONG_RESULT_INCIDENT)
    await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        issue = await feedback.find_known_issue_for_auto_event(session, incident)

    assert issue is None


@pytest.mark.asyncio
async def test_report_about_wrong_data_is_saved_unlinked_and_keeps_its_fingerprint(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    """Сквозная проверка приёма отчёта.

    Отпечаток остаётся записанным — он нужен для склейки повторов и ручной
    привязки. Меняется только его право быть основанием для матча.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "ingest.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    incident = feedback.FeedbackIncident(**WRONG_RESULT_INCIDENT)
    await _issue_with_fingerprint_of(session_factory, incident)

    result = await feedback.create_feedback_report(
        credentials=make_runtime_credentials("clinic", "secret"),
        category="bug",
        severity="medium",
        summary="Report AI returned exactly 1000 rows and stopped before the end date",
        details="Saved report reported limited=false and total=1000 but rows stop early.",
        related_tool="get_report_ai_job_data",
        params_shape=["job_id"],
    )

    async with session_factory() as session:
        report = (
            await session.execute(
                select(AgentFeedbackReport).where(
                    AgentFeedbackReport.id == result["feedback_id"]
                )
            )
        ).scalar_one()

    assert result["known_issue"] is None
    assert report.known_issue_id is None
    assert report.status == feedback.FEEDBACK_STATUS_NEW
    assert report.error_fingerprint_hash == feedback.build_error_fingerprint_hash(incident)


@pytest.mark.asyncio
async def test_refusal_is_logged_with_a_reason(
    sqlite_session_factory_builder,
    tmp_path: Path,
    caplog,
    feedback_pepper,
) -> None:
    """Отказ не должен быть немым: разбор обязан видеть, что совпадения не было
    не потому, что проблемы нет, а потому что основания не было."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "logged.db")
    incident = feedback.FeedbackIncident(**WRONG_RESULT_INCIDENT)
    await _issue_with_fingerprint_of(session_factory, incident)

    with caplog.at_level("INFO"):
        async with session_factory() as session:
            await feedback.find_known_issue_match(session, incident)

    events = [
        record for record in caplog.records
        if getattr(record, "event_name", "") == "known_issue_match_skipped_no_error_signal"
    ]
    assert events, "отказ от привязки не оставил следа в логе"
    assert getattr(events[0], "related_tool", None) == "get_report_ai_job_data"


@pytest.mark.asyncio
async def test_incident_built_from_an_exception_always_carries_an_error_signal(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Родственный путь: подсказка агенту при отказе инструмента.

    `build_incident_from_exception` кладёт имя класса исключения в `error_code`,
    поэтому признак ошибки там есть всегда. Тест прибивает это свойство: если
    когда-нибудь код перестанет его заполнять, запрет этапа 295 молча выключит
    подсказки на отказах — самый частый и самый полезный путь.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "from-exc.db")
    incident = feedback.build_incident_from_exception(
        "get_report_ai_job_data", RuntimeError("upstream refused the export")
    )
    issue_id = await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert feedback._has_error_signal(incident) is True
    assert match is not None
    assert match.id == issue_id


# --- Внешнее ревью 04.09.2026, два принятых finding'а -----------------------
#
# Оба поля, по которым считается «признак ошибки», заполняет сам агент: у
# `report_problem` это `http_status: int | None` и `error_code: str`. Описание
# инструмента прямо зовёт сообщать и про успешные вызовы («even when the tool
# call succeeded but the result does not let you answer the user well»), значит
# оба поля придут заполненными и у отчёта про неверные данные. Если считать
# признаком любое значение, запрет обходится и дефект возвращается — с тем же
# слабым отпечатком, только с добавленной константой.


@pytest.mark.asyncio
async def test_successful_http_status_is_not_an_error_signal(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """`http_status=200` — это «вызов прошёл», а не признак отказа.

    Отпечаток при нём — `related_tool + 200 + params_shape`, то есть ровно та
    же склейка всех отчётов про инструмент, от которой этап и защищается.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "http-200.db")
    incident = feedback.FeedbackIncident(
        related_tool="get_report_ai_job_data",
        http_status=200,
        params_shape=["job_id"],
    )
    await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 403, 404, 500, 502])
async def test_failing_http_status_is_an_error_signal(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
    status: int,
) -> None:
    """Отказ по HTTP признаком остаётся — иначе выключим основной путь."""
    session_factory = await sqlite_session_factory_builder(tmp_path / f"http-{status}.db")
    incident = feedback.FeedbackIncident(
        related_tool="get_clients",
        http_status=status,
        params_shape=["limit"],
    )
    issue_id = await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is not None
    assert match.id == issue_id


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["-", "—", "none", "None", "null", "N/A", "n/a", "unknown"])
async def test_placeholder_error_code_is_not_an_error_signal(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
    code: str,
) -> None:
    """Заглушка вместо кода ошибки не является кодом ошибки.

    `-` — не выдумка: именно так `triage_agent_feedback.py recent` печатает
    отсутствующий код, и агент, читавший вывод разбора, повторит эту строку.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "placeholder.db")
    incident = feedback.FeedbackIncident(
        related_tool="get_report_ai_job_data",
        error_code=code,
        params_shape=["job_id"],
    )
    await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is None, f"заглушка {code!r} прошла как признак ошибки"


@pytest.mark.asyncio
async def test_real_error_code_still_counts(
    sqlite_session_factory_builder,
    tmp_path: Path,
    feedback_pepper,
) -> None:
    """Настоящий код ошибки остаётся признаком."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "real-code.db")
    incident = feedback.FeedbackIncident(
        related_tool="get_clients",
        error_code="ToolError",
        params_shape=["limit"],
    )
    issue_id = await _issue_with_fingerprint_of(session_factory, incident)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(session, incident)

    assert match is not None
    assert match.id == issue_id

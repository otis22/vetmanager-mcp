"""Этап 305: правила пишутся из настоящих падений, а не из жалоб.

Ревизия 05.09.2026 прогнала 11 правил против боевых текстов — совпадений ноль.
Причина оказалась в адресах: правила названы на `create_admission`,
`get_breeds`, `tool_search`, а падает совсем другое. Правила писались из
отчётов — из того, на что жаловались, — а не из того, что ломается.

Корпус ниже — не выдуманные примеры. Это тексты из Sentry за 90 дней с числом
событий за каждым, снятые 06.09.2026. Инцидент собирается ровно так же, как в
рантайме: из живого исключения того класса, который его и бросает на бою.

Каждый случай проверяется в двух формах текста — как его видит наш код и как он
выглядит в Sentry с обёрткой FastMCP. До этапа 306 вторая форма была
единственной, которую вообще можно было увидеть, и на ней легко ошибиться.

Этап 307 добавил в корпус два класса ошибок вызывающего: с разделением
приглашения и playbook они наконец достижимы.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from agent_feedback_service import (
    build_incident_from_exception,
    match_rules,
    validate_agent_playbook,
    validate_match_rules_json,
)
from exceptions import (
    ToolInputError,
    VetmanagerError,
    VetmanagerUpstreamUnavailable,
    reportable_error,
)
from filters import SortPropertyValidationError
from scripts.seed_known_issues import SEED_ISSUES


@dataclass(frozen=True)
class RealFailure:
    """Настоящий отказ с бою: сколько раз случился и чем должен закрываться."""

    events: int
    tool: str
    exc: BaseException
    covered_by: str | None  # slug правила или None, если правила быть не должно
    note: str


CORPUS: tuple[RealFailure, ...] = (
    # --- контракт фильтра и сортировки: апстрим отвечает 406 ---
    RealFailure(
        4, "get_admissions",
        VetmanagerError("Upstream API error (HTTP 406) — Invalid sort item name: <date_admission>.", 406),
        "upstream-rejects-field-name", "PYTHON-8",
    ),
    RealFailure(
        4, "get_cassa_closes",
        VetmanagerError("Upstream API error (HTTP 406) — Invalid filter item name: <close_date>.", 406),
        "upstream-rejects-field-name", "PYTHON-5",
    ),
    RealFailure(
        3, "get_invoices",
        VetmanagerError("Upstream API error (HTTP 406) — Invalid filter item: property is required.", 406),
        "upstream-rejects-field-name", "PYTHON-S",
    ),
    RealFailure(
        3, "get_users",
        VetmanagerError("Upstream API error (HTTP 406) — Invalid sort item: property is required.", 406),
        "upstream-rejects-field-name", "PYTHON-12",
    ),
    RealFailure(
        1, "get_medical_cards",
        VetmanagerError("Upstream API error (HTTP 406) — Invalid sort item: property is required.", 406),
        "upstream-rejects-field-name", "PYTHON-V",
    ),
    # --- тот же класс, но отказал наш собственный валидатор ---
    RealFailure(
        2, "get_cassa_closes",
        SortPropertyValidationError(
            "Unknown sort property 'close_date'. Allowed properties: amount, date, id, status."
        ),
        "upstream-rejects-field-name", "наш валидатор, PYTHON-7",
    ),
    # --- запись без клиники ---
    RealFailure(
        5, "create_medical_card",
        VetmanagerError("Upstream API error (HTTP 500) — No Clinic selected", 500),
        "write-needs-clinic", "PYTHON-15",
    ),
    # --- экспорт отчёта ---
    RealFailure(
        4, "get_report_export_download",
        reportable_error("Getting report export file failed HTTP 404."),
        "report-export-not-available", "PYTHON-H",
    ),
    # --- ошибка вызывающего: достижимо с этапа 307 ---
    RealFailure(
        4, "save_report_ai_job_as_report",
        ToolInputError(
            "Upstream API error (HTTP 409): INVALID_TRANSITION — "
            "Сохранение недоступно из статуса 'needs_confirmation'"
        ),
        "report-ai-save-needs-confirmation", "PYTHON-W",
    ),
    RealFailure(
        2, "start_report_export",
        ToolInputError(
            "Report is not REST-exportable: Vetmanager denied StartReport for this report_id."
        ),
        "report-export-not-available", "PYTHON-N",
    ),
    # --- то, на что правила в этом этапе быть НЕ должно ---
    RealFailure(
        5181, "get_invoice_by_id",
        VetmanagerUpstreamUnavailable("VM API circuit breaker half-open for alternativa; probe already in flight"),
        None, "предохранитель — отдельный этап, две строки в журнал на каждый отказ",
    ),
    RealFailure(
        657, "get_invoice_by_id",
        VetmanagerError("Timeout requesting Vetmanager upstream. Please retry shortly.", 504),
        None, "таймаут — там же",
    ),
)

# Раздел «недостижимо по замыслу» опустел на этапе 307. Он существовал ради
# двух классов выше: они стали `ToolInputError` уже после того, как их события
# записались в Sentry (этап 265.6 — 27.08.2026, этап 280 — 04.09.2026), и
# потому несли подпись механизма, не проходя через него сегодня. Этап 307
# разделил приглашение сообщить о дефекте и доставку playbook — обвинение
# по-прежнему выключено, а playbook доезжает, и правила под них стали
# осмысленными.
#
# Урок, ради которого этот комментарий остаётся: корпус из Sentry показывает
# поведение кода **на момент события**, а не сегодняшнее.


# Этап 307, найдено ревью дифа. `INVALID_TRANSITION` — один код на четыре
# разные ситуации (`tools/report_ai.py:682`): подтверждение не из
# `needs_confirmation`, сохранение из неподходящего статуса, запрос данных до
# сохранения, недопустимый переход. Правило под одну из них не смеет отвечать
# за остальные: playbook «сначала подтверди кандидата» на запросе данных из
# `ready_to_save` уводит агента не туда.
#
# Мало сузить правило до инструмента: один и тот же
# `save_report_ai_job_as_report` отказывает и из `queued`, и из
# `needs_confirmation`, а подтверждать кандидата можно только во втором
# случае. Найдено вторым прогоном ревью дифа.
#
# Корпус выше состоит из настоящих событий Sentry и потому эти случаи не
# ловит — их там просто не было. Точность проверяется отдельно.
OTHER_TRANSITIONS: tuple[RealFailure, ...] = (
    RealFailure(
        0, "get_report_ai_job_data",
        ToolInputError(
            "Upstream API error (HTTP 409): INVALID_TRANSITION — "
            "Данные доступны только для job со статусом saved или existing_report_matched"
        ),
        None, "данные запрошены до сохранения",
    ),
    RealFailure(
        0, "save_report_ai_job_as_report",
        ToolInputError(
            "Upstream API error (HTTP 409): INVALID_TRANSITION — "
            "Сохранение недоступно из статуса queued"
        ),
        None, "тот же инструмент, но статус queued",
    ),
    RealFailure(
        0, "confirm_report_ai_job_candidate",
        ToolInputError(
            "Upstream API error (HTTP 409): INVALID_TRANSITION — "
            "Подтверждение доступно только из статуса needs_confirmation"
        ),
        None, "подтверждение не из needs_confirmation",
    ),
)


@pytest.mark.parametrize(
    "failure", OTHER_TRANSITIONS, ids=[f.note for f in OTHER_TRANSITIONS]
)
def test_one_upstream_code_does_not_hand_out_one_playbook(failure: RealFailure) -> None:
    """Правило отвечает за свою ситуацию, а не за весь код апстрима."""
    matched = _rules_matching(failure)

    assert "report-ai-save-needs-confirmation" not in matched, (
        f"playbook про подтверждение кандидата выдан на другой отказ: {failure.note}"
    )


def _seed_by_slug() -> dict[str, object]:
    return {item.slug: item for item in SEED_ISSUES}


def _rules_matching(failure: RealFailure) -> set[str]:
    """Какие seed-правила совпадают с этим отказом — в обеих формах текста."""
    matched: set[str] = set()
    wrapped = reportable_error(f"Error calling tool '{failure.tool}': {failure.exc}")
    for incident_exc in (failure.exc, wrapped):
        incident = build_incident_from_exception(failure.tool, incident_exc)
        for item in SEED_ISSUES:
            if match_rules(json.dumps(item.match_rules), incident):
                matched.add(item.slug)
    return matched


@pytest.mark.parametrize(
    "failure",
    [f for f in CORPUS if f.covered_by],
    ids=[f"{f.tool}-{f.note}" for f in CORPUS if f.covered_by],
)
def test_every_real_failure_class_has_a_rule(failure: RealFailure) -> None:
    """Сторож принимается красным: сегодня на этом корпусе ноль совпадений."""
    matched = _rules_matching(failure)

    assert failure.covered_by in matched, (
        f"{failure.events} событий за 90 дней ({failure.note}) не закрыты ни одним правилом; "
        f"совпало: {sorted(matched) or 'ничего'}"
    )


@pytest.mark.parametrize(
    "failure",
    [f for f in CORPUS if not f.covered_by],
    ids=[f"{f.tool}-no-rule" for f in CORPUS if not f.covered_by],
)
def test_the_loudest_failures_stay_without_a_rule(failure: RealFailure) -> None:
    """Правило на предохранитель включило бы запись на 6 000 отказов.

    Событие пишется дважды на каждое совпадение — `injection` и `auto`, — и ни
    дедупа, ни потолка у этой записи нет. Пока это так, правило на самый частый
    отказ заводить нельзя, и случайно завести его тоже нельзя.
    """
    assert _rules_matching(failure) == set(), (
        f"{failure.events} событий за 90 дней внезапно закрыты правилом: {failure.note}"
    )


def test_every_rule_carries_a_playbook() -> None:
    """Правило без playbook даёт событие `auto`, но до агента не доходит.

    `find_known_issue_match` пропускает кандидата, у которого playbook не
    разбирается, — такое правило работает только на бумаге.
    """
    without = [
        item.slug for item in SEED_ISSUES
        if validate_agent_playbook(json.dumps(item.agent_playbook)) is None
    ]

    assert without == []


def test_every_rule_is_valid_and_says_something() -> None:
    """Пустой список условий совпадает со всем — такому правилу тут не место."""
    for item in SEED_ISSUES:
        rules = validate_match_rules_json(json.dumps(item.match_rules))
        assert rules is not None, item.slug
        assert rules["all"], f"{item.slug}: правило без условий совпадёт с любым отказом"


def test_the_older_rules_still_match_what_they_were_written_for() -> None:
    """Новые правила не должны ломать прежние семь.

    Проверка идёт от самих правил: у каждого берётся его инструмент и первый
    текстовый маркер, и правило обязано узнать собственный отказ.
    """
    for item in SEED_ISSUES:
        # Условий может быть несколько, и все они обязательны. Внутри условия
        # смотрим на оператор: `contains_any` довольствуется одним маркером,
        # `contains_all` требует всех. Этап 307 завёл первое правило со вторым
        # оператором, и прежняя выборка «первый маркер каждого условия» стала
        # собирать текст, которому правило не отвечает.
        markers: list[str] = []
        for condition in item.match_rules["all"]:
            if condition["field"] != "normalized_error_text":
                continue
            values = condition["value"]
            markers.extend(values if condition["op"] == "contains_all" else values[:1])
        if not markers or not item.related_tool:
            continue
        sample = reportable_error("upstream failed: " + " ".join(markers))
        incident = build_incident_from_exception(item.related_tool, sample)

        assert match_rules(json.dumps(item.match_rules), incident), (
            f"{item.slug} не узнаёт собственный отказ"
        )


@pytest.mark.parametrize(
    "failure",
    [f for f in CORPUS if f.covered_by],
    ids=[f"{f.tool}-{f.note}" for f in CORPUS if f.covered_by],
)
def test_exactly_one_rule_answers_each_failure(failure: RealFailure) -> None:
    """Совпасть должно ровно одно правило.

    Найдено ревью дифа: проверки «нужное правило есть среди совпавших» мало.
    Кандидат выбирается первым по `priority`, и второе, более широкое правило
    молча заберёт отказ себе — тест при этом останется зелёным.
    """
    matched = _rules_matching(failure)

    assert matched == {failure.covered_by}, (
        f"на {failure.note} ответило больше одного правила: {sorted(matched)}"
    )

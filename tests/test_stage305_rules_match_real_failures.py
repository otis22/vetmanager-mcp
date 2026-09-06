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
from exceptions import VetmanagerError, VetmanagerUpstreamUnavailable, reportable_error
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
    # --- Report AI: сохранение из неподтверждённого статуса ---
    RealFailure(
        4, "save_report_ai_job_as_report",
        reportable_error(
            "Upstream API error (HTTP 409): INVALID_TRANSITION — "
            "Сохранение недоступно из статуса 'needs_confirmation'"
        ),
        "report-ai-save-needs-confirmation", "PYTHON-W",
    ),
    # --- экспорт отчёта ---
    RealFailure(
        4, "get_report_export_download",
        reportable_error("Getting report export file failed HTTP 404."),
        "report-export-not-available", "PYTHON-H",
    ),
    RealFailure(
        2, "start_report_export",
        reportable_error(
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
        # У правила может быть несколько текстовых условий, и все они
        # обязательны: берём по одному маркеру из каждого.
        markers = [
            condition["value"][0]
            for condition in item.match_rules["all"]
            if condition["field"] == "normalized_error_text"
        ]
        if not markers or not item.related_tool:
            continue
        sample = reportable_error("upstream failed: " + " ".join(markers))
        incident = build_incident_from_exception(item.related_tool, sample)

        assert match_rules(json.dumps(item.match_rules), incident), (
            f"{item.slug} не узнаёт собственный отказ"
        )

"""Этап 296 — `limited` у данных ИИ-отчёта не признак обрезки.

Отчёт #62: Report AI отдал ровно 1000 строк с `limited=false` и оборвался.
Агент поверил флагу, потому что описание инструмента велело ему верить.

Механика из исходников Ветменеджера, а не из наблюдения:

    AiReportRenderer::VIEW_ROW_LIMIT = 1000
    $sql = SqlRowLimiter::apply($sql, self::VIEW_ROW_LIMIT);
    return ['data' => $rows, 'total' => count($rows), ...];

    JobService::DATA_ROW_LIMIT = 10000
    'limited' => $total > self::DATA_ROW_LIMIT

Рендер обрезает SQL на 1000 строках и отдаёт `total` от уже обрезанного набора.
Значит `limited` считается как `1000 > 10000` и **структурно всегда `false`**.

Тесты держат две вещи: описание не называет `limited` признаком полноты, и
рантайм сам говорит про обрезку на 1000 строках, не дожидаясь флага, которого
не будет.
"""

from __future__ import annotations

import pathlib

import pytest

from tool_descriptions import compose_tool_description
from tools.report_ai import (
    REPORT_AI_DATA_ROW_LIMIT,
    REPORT_AI_RENDERER_ROW_LIMIT,
    _annotate_report_ai_data_payload,
)


def _payload(*, rows: int, total: int, limited: bool) -> dict:
    return {
        "data": {
            "columns": ["id", "amount"],
            "rows": [{"id": i, "amount": 1} for i in range(rows)],
            "total": total,
            "limited": limited,
            "csv_export_url": "/rest/api/report/startReport?report_id=7",
        }
    }


def test_the_two_upstream_limits_are_different_numbers() -> None:
    """Их сведение в одну величину и есть исходная ошибка описания."""
    assert REPORT_AI_RENDERER_ROW_LIMIT == 1000
    assert REPORT_AI_DATA_ROW_LIMIT == 10000
    assert REPORT_AI_RENDERER_ROW_LIMIT < REPORT_AI_DATA_ROW_LIMIT


def test_description_does_not_present_limited_as_the_truncation_signal() -> None:
    description = compose_tool_description("get_report_ai_job_data") or ""

    assert "1000" in description, "агент не узнает настоящий предел данных"
    assert "10000" not in description, (
        "описание всё ещё называет пределом данных величину выдачи, "
        "которая для ИИ-отчёта не срабатывает никогда"
    )


def test_description_says_limited_cannot_be_trusted_here() -> None:
    """Мало назвать верное число: без явного запрета `limited=false`
    остаётся допустимым прочтением «данные полные»."""
    description = (compose_tool_description("get_report_ai_job_data") or "").lower()

    assert "limited" in description
    assert "not" in description or "never" in description


def test_exactly_the_renderer_cap_is_reported_as_probable_truncation() -> None:
    """Главный случай отчёта #62: 1000 строк и `limited=false`."""
    annotated = _annotate_report_ai_data_payload(
        _payload(rows=1000, total=1000, limited=False)
    )

    guidance = annotated["data"].get("mcp_large_result_guidance")
    assert guidance is not None, "рантайм промолчал ровно там, где обрезали"
    assert guidance["code"] == "report_ai_probable_truncation"
    assert guidance["renderer_row_limit"] == REPORT_AI_RENDERER_ROW_LIMIT
    assert guidance["export_available"] is True


def test_truncation_guidance_does_not_depend_on_the_limited_flag() -> None:
    """Флаг может прийти любым — вывод об обрезке делается по числу строк."""
    annotated = _annotate_report_ai_data_payload(
        _payload(rows=1000, total=1000, limited=True)
    )

    guidance = annotated["data"].get("mcp_large_result_guidance")
    assert guidance is not None


def test_short_result_is_left_alone() -> None:
    """Отчёт, уместившийся целиком, подсказку получать не должен."""
    annotated = _annotate_report_ai_data_payload(
        _payload(rows=42, total=42, limited=False)
    )

    assert "mcp_large_result_guidance" not in annotated["data"]


def test_large_result_guidance_above_the_old_threshold_still_works() -> None:
    """Прежний случай — объём близок к пределу выдачи — не сломан."""
    annotated = _annotate_report_ai_data_payload(
        _payload(rows=9500, total=9500, limited=False)
    )

    guidance = annotated["data"].get("mcp_large_result_guidance")
    assert guidance is not None
    assert guidance["code"] == "report_ai_large_result"


def test_payload_without_data_is_untouched() -> None:
    assert _annotate_report_ai_data_payload({"data": None}) == {"data": None}


@pytest.mark.parametrize("rows", [999, 1001])
def test_only_the_exact_cap_triggers_the_truncation_verdict(rows: int) -> None:
    """Обрезка узнаётся по точному совпадению с пределом рендера.

    999 строк — отчёт кончился сам; 1001 строка для ИИ-отчёта недостижима, и
    если такое придёт, значит наше понимание апстрима устарело: в этом случае
    вердикт «обрезано» был бы выдумкой.
    """
    annotated = _annotate_report_ai_data_payload(
        _payload(rows=rows, total=rows, limited=False)
    )
    guidance = annotated["data"].get("mcp_large_result_guidance")

    if guidance is not None:
        assert guidance["code"] != "report_ai_probable_truncation"


# --- Внешнее ревью 04.09.2026: те же слова жили ещё в двух местах ------------
#
# Ревьюер нашёл старый контракт в README и в описаниях экспортных инструментов.
# Это ровно тот же класс, что и сам этап: утверждение живёт в нескольких копиях,
# правится одна, остальные продолжают учить неверному. Тест держит все копии.


def test_export_tool_descriptions_do_not_wait_for_an_impossible_flag() -> None:
    """Экспорт — правильный ответ на обрезку, но триггером у него стоял флаг,
    которого для данных ИИ-отчёта не бывает."""
    for tool_name in ("start_report_export", "get_report_ai_job_export"):
        description = compose_tool_description(tool_name) or ""
        assert "limited=true" not in description, (
            f"{tool_name}: экспорт по-прежнему ждёт недостижимого limited=true"
        )


def test_readme_states_the_real_cap() -> None:
    """README — операционная инструкция для людей, и она учила тому же."""
    readme = pathlib.Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert "10000 JSON rows" not in text, "README всё ещё называет предел выдачи пределом данных"
    assert "`get_report_ai_job_data` отдаёт не более **1000 строк**" in text
    assert "структурно всегда `false`" in text

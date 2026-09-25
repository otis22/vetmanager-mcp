"""Этап 280 — отказ вызывающего и наша поломка не должны выглядеть одинаково.

`_tool_error_from_vm` объявлял **любой** отказ Report AI нашим дефектом:
`reportable_error(str(exc))`. Значит агент, попросивший данные до сохранения
отчёта, получал приглашение завести баг про собственную последовательность
вызовов — и Sentry-issue в придачу.

Разбор кодов апстрима (`JobException` в `vetmanager-extjs`) показал, что
классифицировать их скопом нельзя, как и предупреждал сам этап:

    VALIDATION_ERROR    — и «Некорректный id job» от вызывающего,
                          и «{поле} должен быть целым числом» о запросе,
                          который собрали мы;
    FORBIDDEN           — и «Нет доступа к этой job» (вызывающий),
                          и «Клиника не определена» (не прошла авторизация);
    INTENT_REJECTED     — «LLM не вернула распознанную структуру», то есть
                          распознаватель апстрима, а не формулировка агента;
    SANITIZER_REJECTED  — санитайзер отвергает SQL, сгенерированный апстримом;
    PREVIEW_FAILED,
    SAVE_FAILED         — апстрим не справился.

Однозначен ровно один код порядка вызовов. Все четыре места, где апстрим поднимает
`INVALID_TRANSITION`, — про статус job против запрошенной операции:
подтверждение не из `needs_confirmation`, сохранение из неподходящего статуса,
данные до сохранения, недопустимый переход. Это всегда порядок вызовов, то есть
вызывающий, и на это у агента есть понятное следующее действие.

После этапа 350 сырой текст ошибки может содержать SQL. Код класса ошибки и
safe guidance сохраняются, но сообщение апстрима больше не копируется агенту.
Остальные коды остаются приглашающими к отчёту сознательно.
"""

from __future__ import annotations

import pytest

from exceptions import ToolInputError, VetmanagerError
from tools.report_ai import _tool_error_from_vm
from agent_feedback_service import should_skip_report_hint


def _vm_error(code: str | None, message: str = "Upstream API error (HTTP 409)") -> VetmanagerError:
    return VetmanagerError(message, status_code=409, error_code=code)


def test_wrong_call_order_is_not_our_defect() -> None:
    """Главный случай: данные запрошены до сохранения отчёта."""
    exc = _tool_error_from_vm(
        _vm_error(
            "INVALID_TRANSITION",
            "Данные доступны только для job со статусом saved или existing_report_matched",
        )
    )

    assert isinstance(exc, ToolInputError)
    assert should_skip_report_hint(exc) is True
    assert "Read the current job status" in str(exc)
    assert "saved или existing_report_matched" not in str(exc)


@pytest.mark.parametrize(
    "code",
    ["VALIDATION_ERROR", "FORBIDDEN", "INTENT_REJECTED", "SANITIZER_REJECTED",
     "PREVIEW_FAILED", "SAVE_FAILED"],
)
def test_ambiguous_codes_stay_reportable(code: str) -> None:
    """Каждый из этих кодов поднимается и на вине вызывающего, и на нашей.

    Отнести их к вине вызывающего значит замолчать собственные поломки —
    ровно то, от чего этап предостерегает.
    """
    exc = _tool_error_from_vm(_vm_error(code))

    assert not isinstance(exc, ToolInputError)
    assert should_skip_report_hint(exc) is False


def test_unknown_code_stays_reportable() -> None:
    """Апстрим может завести новый код; по умолчанию он наш, пока не разобран."""
    exc = _tool_error_from_vm(_vm_error("SOMETHING_NEW_UPSTREAM"))

    assert not isinstance(exc, ToolInputError)


def test_error_without_a_code_stays_reportable() -> None:
    exc = _tool_error_from_vm(_vm_error(None))

    assert not isinstance(exc, ToolInputError)


def test_ambiguous_code_does_not_echo_raw_sql() -> None:
    exc = _tool_error_from_vm(_vm_error("PREVIEW_FAILED", "SQLSTATE SELECT secret"))
    assert "SQLSTATE" not in str(exc)
    assert not isinstance(exc, ToolInputError)

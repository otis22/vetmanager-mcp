from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import inspect
from functools import wraps

import depersonalization
from depersonalization import contains_addressed_placeholder
from agent_feedback_service import augment_tool_error, should_skip_report_hint
from error_tracking import set_affected_account
from exceptions import (
    AuthError,
    NotFoundError,
    RateLimitError,
    ToolInputError,
    VetmanagerError,
    reportable_error,
)
from filters import FilterPropertyValidationError, SortPropertyValidationError
from privacy_utils import redact_sensitive_output_fields, redact_tool_error
from runtime_auth import use_runtime_credentials
from service_metrics import (
    record_placeholder_argument_rejection,
    record_sanitizer_failure,
)
from tool_scope_security import (
    BASELINE_ALLOWED_TOOLS,
    AuthChallengeToolError,
    _ensure_tool_scopes_allowed,
)
from tool_access_registry import (
    TOOL_REQUIRED_SCOPES,
)

# Этап 306: до этой правки обёртка ловила только `ToolError`, и механизм
# известных проблем видел 0.2% отказов. Инструменты в массе бросают
# `VetmanagerError` и наследников; в `ToolError` их превращал FastMCP уровнем
# выше, уже после обёртки, — поэтому в Sentry всё выглядело как `ToolError`.
REPORTABLE_UPSTREAM_ERRORS = (
    VetmanagerError,
    FilterPropertyValidationError,
    SortPropertyValidationError,
)
# Отказы, которые не являются дефектом продукта: приглашать сообщить о них как
# о баге значит учить агента заводить баги на нормальную работу системы.
# `NotFoundError` — 404 от десятков `get_*_by_id`, то есть устаревший
# идентификатор. `AuthError` — отказ доступа. `RateLimitError` — наш
# собственный ограничитель частоты, апстрим его не бросает вовсе, и вместе с
# подписью он потерял бы `retry_after_seconds`.
NOT_A_DEFECT_ERRORS = (AuthError, NotFoundError, RateLimitError)


# Stage 275: what a report returns is shaped by generated SQL, so its columns
# cannot be recognised by name. These tools get value-level cleaning on top;
# ordinary tools must not, or predictable fields start losing real data.
REPORT_TOOLS = frozenset({
    "create_report_ai_job",
    "confirm_report_ai_job_candidate",
    "get_report_ai_job",
    "get_report_ai_job_data",
    "get_report_ai_job_export",
    "save_report_ai_job_as_report",
    "start_report_export",
})
from vetmanager_client import resolve_runtime_credentials


async def _with_known_issue_hint(
    tool_name: str, credentials, exc, *, incident_source=None, blame_product: bool = True
):
    """Подсказка про известную проблему поверх отказа, с редактированием на выходе.

    Общая для обеих веток обёртки: собственного `ToolError` и отказа апстрима
    (этап 306). Держится одной функцией намеренно — пока это были два
    одинаковых блока рядом, любая правка одного молча расходилась со вторым.
    """
    # Параметр передаётся только когда он есть: путь собственного `ToolError`
    # вызывает `augment_tool_error` ровно так же, как до этапа 306, и подмены
    # этой функции в тестах не обязаны знать про новый аргумент.
    extra = {"incident_source": incident_source} if incident_source is not None else {}
    if not blame_product:
        extra["blame_product"] = False
    augmented = await augment_tool_error(tool_name, credentials, exc, **extra)
    return redact_tool_error(augmented) if type(augmented) is ToolError else augmented


def _reject_placeholder_arguments(tool_name: str, args: tuple, kwargs: dict) -> None:
    """Адресный плейсхолдер — конечное значение для человека, а не для записи.

    Этап 308 сделал маску похожей на значение, и модель, честно выполнившая
    инструкцию «переноси дословно», записывала её в базу клиники вместо
    фамилии. Подставлять настоящее значение здесь нельзя: контур записи и
    контур чтения моделью не разделены, и подставленное вернулось бы ей через
    чтение той же записи.

    Проверка одинакова для любого токена: плейсхолдер живёт в истории диалога,
    и один и тот же аргумент не может то отклоняться, то портить данные.
    """
    if tool_name in BASELINE_ALLOWED_TOOLS:
        # `report_problem` и помощник промпта ничего не пишут в базу клиники и
        # наверх не ходят. Больше того, отчёт о проблеме — единственное место,
        # где плейсхолдер уместен: этап 299 закрепил, что в отчёте он признак
        # соблюдения контракта, а не риска. Запрет здесь сломал бы обратную
        # связь ровно про тот инцидент, который чинит этот этап.
        return
    if not contains_addressed_placeholder(list(args)) and not contains_addressed_placeholder(kwargs):
        return
    record_placeholder_argument_rejection(tool_name)
    raise ToolInputError(
        "A tool argument contains an addressed placeholder such as "
        "[client:123:last_name]. A placeholder is the final value shown to the "
        "person, not a value to store or send: the application substitutes it "
        "on its side. Pass the real value, omit the field, or let the "
        "application resolve the placeholder before calling this tool."
    )


def _wrap_tool_with_depersonalization(tool_func, *, tool_name: str | None = None):
    resolved_tool_name = tool_name or tool_func.__name__

    @wraps(tool_func)
    async def _wrapped(*args, **kwargs):
        try:
            credentials = await resolve_runtime_credentials()
        except AuthError as exc:
            raise AuthChallengeToolError(
                "Runtime authentication failed.",
                required_scopes=TOOL_REQUIRED_SCOPES.get(resolved_tool_name),
                error=exc.error_code or "invalid_token",
                error_description="OAuth authorization is required for this tool.",
            ) from None
        _ensure_tool_scopes_allowed(resolved_tool_name, credentials)
        set_affected_account(getattr(credentials, "account_id", None))

        with use_runtime_credentials(credentials):
            try:
                # Этап 309. Проверка стоит внутри этого `try` намеренно: этап
                # 307 обрабатывает ошибку вызывающего только здесь. Снаружи
                # ошибка была бы того же типа, но без playbook.
                _reject_placeholder_arguments(resolved_tool_name, args, kwargs)
                result = await tool_func(*args, **kwargs)
            except ToolError as exc:
                if resolved_tool_name in BASELINE_ALLOWED_TOOLS:
                    raise
                if should_skip_report_hint(exc):
                    # Этап 307. Ошибка вызывающего не получает ни приглашения
                    # сообщить о дефекте, ни авто-отчёта — но playbook ей
                    # полезнее всего: он говорит, что сделать вместо.
                    #
                    # Граница по точному типу, а не по `isinstance`:
                    # произвольный подкласс со своей сигнатурой `__init__`
                    # пересобрать нельзя, и augmentation вернула бы другой
                    # объект, потеряв его атрибуты.
                    if type(exc) is not ToolInputError:
                        raise
                    raise await _with_known_issue_hint(
                        resolved_tool_name, credentials, exc, blame_product=False
                    ) from exc
                raise await _with_known_issue_hint(
                    resolved_tool_name,
                    credentials,
                    redact_tool_error(exc) if type(exc) is ToolError else exc,
                ) from exc
            except NOT_A_DEFECT_ERRORS:
                raise
            except REPORTABLE_UPSTREAM_ERRORS as exc:
                # Этап 306: тот же путь, что у собственного ToolError. Наружу
                # уходит ToolError — до этой правки его строил FastMCP уровнем
                # выше, дописывая префикс `Error calling tool 'X':` и оставляя
                # текст апстрима без редактирования приватности.
                if resolved_tool_name in BASELINE_ALLOWED_TOOLS:
                    raise
                # Редактирование идёт до подписи: `redact_tool_error` разбирает
                # аргументы как JSON, а после склейки с подсказкой текст
                # перестаёт быть разбираемым и ушёл бы к клиенту как есть.
                raise await _with_known_issue_hint(
                    resolved_tool_name,
                    credentials,
                    # Пустые args превратили бы отказ в пустую строку — тогда
                    # вызывающий не узнаёт даже, что именно отказало.
                    redact_tool_error(
                        reportable_error(str(exc) or exc.__class__.__name__)
                    ),
                    incident_source=exc,
                ) from exc
            result = redact_sensitive_output_fields(result)
            if not credentials.is_depersonalized:
                return result
            try:
                return depersonalization.sanitize_tool_result(
                    result,
                    report_mode=resolved_tool_name in REPORT_TOOLS,
                    tool_name=resolved_tool_name,
                )
            except Exception:
                record_sanitizer_failure()
                raise reportable_error("Depersonalization failed.") from None

    _wrapped.__signature__ = inspect.signature(tool_func)
    return _wrapped


class _ToolRegistrationProxy:
    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    def tool(self, func=None, **kwargs):
        if func is None:
            def _decorator(actual_func):
                tool_name = kwargs.get("name") or actual_func.__name__
                return self._mcp.tool(
                    _wrap_tool_with_depersonalization(actual_func, tool_name=tool_name),
                    **kwargs,
                )

            return _decorator
        tool_name = kwargs.get("name") or func.__name__
        return self._mcp.tool(_wrap_tool_with_depersonalization(func, tool_name=tool_name), **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._mcp, name)


def register_all(mcp: FastMCP) -> None:
    """Register all entity tool modules with the MCP server."""
    tool_mcp = _ToolRegistrationProxy(mcp)
    from tools.client import register as register_client
    from tools.pet import register as register_pet
    from tools.admission import register as register_admission
    from tools.medical_card import register as register_medical_card
    from tools.invoice import register as register_invoice
    from tools.good import register as register_good
    from tools.user import register as register_user
    from tools.reference import register as register_reference
    from tools.finance import register as register_finance
    from tools.warehouse import register as register_warehouse
    from tools.clinical import register as register_clinical
    from tools.operations import register as register_operations
    from tools.schedule import register as register_schedule
    from tools.feedback import register as register_feedback
    from tools.report_ai import register as register_report_ai

    register_feedback(tool_mcp)
    register_report_ai(tool_mcp)
    register_client(tool_mcp)
    register_pet(tool_mcp)
    register_admission(tool_mcp)
    register_medical_card(tool_mcp)
    register_invoice(tool_mcp)
    register_good(tool_mcp)
    register_user(tool_mcp)
    register_reference(tool_mcp)
    register_finance(tool_mcp)
    register_warehouse(tool_mcp)
    register_clinical(tool_mcp)
    register_operations(tool_mcp)
    register_schedule(tool_mcp)

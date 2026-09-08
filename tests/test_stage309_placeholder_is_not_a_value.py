"""Этап 309 — плейсхолдер перестаёт уезжать в базу клиники как значение.

Этап 308 сделал маску адресной и записал в инструкции сервера: переноси
плейсхолдер дословно «в ответ и в аргументы инструментов». Модель это и делала,
а обёртка чистила только результат — аргументы уходили в инструмент нетронутыми.

`update_client(client_id=123, last_name="[client:123:last_name]")` записывал
плейсхолдер в базу клиники вместо фамилии. Это порча настоящих данных, а не
косметика, и внесена она предыдущим этапом.

Подстановка значений на стороне MCP отклонена: контур записи и контур чтения
моделью не разделены, поэтому подставленное значение вернулось бы модели через
чтение той же записи. Отсюда отказ вместо резолва.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from depersonalization import (
    ADDRESSED_PLACEHOLDER_ENTITIES,
    build_addressed_placeholder,
    contains_addressed_placeholder,
    sanitize_tool_result,
)
from server import mcp
from service_metrics import reset_service_metrics, snapshot_service_metrics
from tests.test_stage130_depersonalization import BASE, bearer_runtime_patch, billing_mock

PLACEHOLDER = "[client:123:last_name]"


@pytest.fixture(autouse=True)
def _clean_metrics():
    reset_service_metrics()
    yield
    reset_service_metrics()


# ── детектор и сборщик — одна пара, а не два независимых мнения ────────────


def test_detector_recognizes_what_the_sanitizer_actually_produced():
    """Тест не сверяет регекс сам с собой: значение производит санитайзер."""
    sanitized = sanitize_tool_result(
        {"data": {"id": 42, "firstName": "Anna"}}, tool_name="get_client_by_id"
    )
    produced = sanitized["data"]["firstName"]
    assert produced != "Anna"
    assert contains_addressed_placeholder(produced)


def test_builder_and_detector_agree():
    built = build_addressed_placeholder("client", 42, "last_name")
    assert contains_addressed_placeholder(built)


def test_detector_finds_a_placeholder_inside_a_longer_string():
    assert contains_addressed_placeholder(f"Уважаемая {PLACEHOLDER}, добрый день")


@pytest.mark.parametrize("entity", sorted(ADDRESSED_PLACEHOLDER_ENTITIES))
def test_every_known_entity_is_recognized(entity):
    assert contains_addressed_placeholder(
        build_addressed_placeholder(entity, 7, "last_name")
    )


@pytest.mark.parametrize(
    "foreign",
    [
        "[note:1:draft]",
        "[TR-1234] старая карточка",
        "размер [10:20:30]",
        "[client:abc:name]",
        "[client:0:name]",
        "client:1:name",
        "",
    ],
)
def test_foreign_lookalikes_pass(foreign):
    """Ложное срабатывание — главная цена проверки для обычных токенов."""
    assert not contains_addressed_placeholder(foreign)


def test_detector_walks_containers_and_dict_keys():
    assert contains_addressed_placeholder({"a": ["b", {"c": PLACEHOLDER}]})
    assert contains_addressed_placeholder({PLACEHOLDER: "value"})
    assert contains_addressed_placeholder(("x", ["y", PLACEHOLDER]))
    assert not contains_addressed_placeholder({"a": ["b", {"c": 42}], "d": None})


def test_cycle_is_rejected_not_recursed_to_death():
    from exceptions import ToolInputError

    loop: dict = {"self": None}
    loop["self"] = loop
    with pytest.raises(ToolInputError):
        contains_addressed_placeholder(loop)


def test_too_deep_structure_is_rejected():
    from exceptions import ToolInputError

    deep: object = "leaf"
    for _ in range(200):
        deep = [deep]
    with pytest.raises(ToolInputError):
        contains_addressed_placeholder(deep)


# ── отказ на живом вызове инструмента ──────────────────────────────────────


async def _call_and_expect_rejection(tool: str, args: dict, *, is_depersonalized: bool):
    route = respx.route(host__regex=r".*").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch(
        is_depersonalized=is_depersonalized
    )
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool(tool, args)
    return excinfo.value, route


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("update_client", {"client_id": 123, "last_name": PLACEHOLDER}),
        ("create_client", {"first_name": "Anna", "last_name": PLACEHOLDER}),
        ("send_message_to_users", {
            "message": f"Уважаемая {PLACEHOLDER}", "campaign": "c", "user_ids": [1]}),
        ("send_message_to_all", {"message": PLACEHOLDER, "campaign": "c"}),
        ("send_message_to_roles", {
            "message": PLACEHOLDER, "campaign": "c", "roles": ["doctor"]}),
    ],
)
async def test_write_tools_reject_a_placeholder_argument(tool, args):
    error, route = await _call_and_expect_rejection(tool, args, is_depersonalized=True)
    assert "placeholder" in str(error).lower()
    # Главное: наверх ничего не ушло.
    assert not any(
        "vetmanager.cloud" in str(call.request.url) and "billing" not in str(call.request.url)
        for call in route.calls
    )


@pytest.mark.asyncio
@respx.mock
async def test_a_tool_outside_the_listed_ones_is_covered_too():
    """Проверка общая, а не список: перечисление в PRD не является контрактом."""
    error, _ = await _call_and_expect_rejection(
        "update_user", {"user_id": 5, "last_name": PLACEHOLDER}, is_depersonalized=True
    )
    assert "placeholder" in str(error).lower()


@pytest.mark.asyncio
@respx.mock
async def test_reading_with_a_placeholder_is_rejected_too():
    """`get_clients(name=…)` с плейсхолдером — бессмысленный запрос."""
    error, _ = await _call_and_expect_rejection(
        "get_clients", {"name": PLACEHOLDER}, is_depersonalized=True
    )
    assert "placeholder" in str(error).lower()


@pytest.mark.asyncio
@respx.mock
async def test_placeholder_nested_in_a_filter_is_rejected():
    error, _ = await _call_and_expect_rejection(
        "get_clients",
        {"filter": [{"property": "last_name", "value": PLACEHOLDER}]},
        is_depersonalized=True,
    )
    assert "placeholder" in str(error).lower()


@pytest.mark.asyncio
@respx.mock
async def test_an_ordinary_token_is_rejected_the_same_way():
    """Плейсхолдер живёт в истории диалога — режим токена его не отменяет.

    Режимозависимое поведение хуже ложного срабатывания: один и тот же
    артефакт протокола не может то отклоняться, то портить данные.
    """
    error, _ = await _call_and_expect_rejection(
        "update_client",
        {"client_id": 123, "last_name": PLACEHOLDER},
        is_depersonalized=False,
    )
    assert "placeholder" in str(error).lower()


@pytest.mark.asyncio
@respx.mock
async def test_error_text_points_away_from_retrying():
    error, _ = await _call_and_expect_rejection(
        "update_client",
        {"client_id": 123, "last_name": PLACEHOLDER},
        is_depersonalized=True,
    )
    text = str(error).lower()
    # Повтор того же вызова ничего не изменит — ошибка обязана сказать, что делать.
    assert "real value" in text or "actual value" in text
    assert "again" not in text.replace("against", "")


@pytest.mark.asyncio
@respx.mock
async def test_clean_arguments_still_reach_the_tool():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/client/123").mock(
        return_value=httpx.Response(200, json={"data": {"id": 123}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=True)
    with headers_patch, runtime_patch:
        await mcp.call_tool("update_client", {"client_id": 123, "last_name": "Иванова"})
    assert route.called


# ── наблюдаемость ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_rejection_is_counted_with_the_tool_name_only():
    await _call_and_expect_rejection(
        "update_client",
        {"client_id": 123, "last_name": PLACEHOLDER},
        is_depersonalized=True,
    )
    counter = snapshot_service_metrics()["placeholder_argument_rejections_total"]
    assert counter.get("update_client") == 1
    # Ни значения, ни пути до него в метрике быть не может: там что угодно.
    assert all(PLACEHOLDER not in key for key in counter)
    assert all("last_name" not in key for key in counter)


# ── инструкции сервера ─────────────────────────────────────────────────────


def test_server_instructions_no_longer_ask_to_carry_it_into_arguments():
    from server import mcp as server_mcp

    instructions = server_mcp.instructions or ""
    assert "placeholder" in instructions.lower()
    assert "into tool arguments" not in instructions.lower()


@pytest.mark.asyncio
@respx.mock
async def test_rejection_goes_through_the_stage_307_handling():
    """Место проверки — часть требования, а не деталь реализации.

    Поставить её до `try` вокруг вызова инструмента значит получить ошибку
    того же типа, но мимо обработки этапа 307: без playbook и без ветки
    «ошибка вызывающего». Снаружи это выглядит одинаково, поэтому сторож
    смотрит именно на вызов augmentation.
    """
    from unittest.mock import AsyncMock, patch

    from exceptions import ToolInputError

    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch(is_depersonalized=True)
    with headers_patch, runtime_patch:
        augment = AsyncMock(side_effect=lambda _t, _c, exc, **kwargs: exc)
        with patch("tools.augment_tool_error", augment):
            with pytest.raises(ToolInputError):
                await mcp.call_tool(
                    "update_client", {"client_id": 123, "last_name": PLACEHOLDER}
                )

    assert augment.await_count == 1
    # Обвинение выключено — это ошибка вызывающего; доставка playbook нет.
    assert augment.await_args.kwargs.get("blame_product") is False

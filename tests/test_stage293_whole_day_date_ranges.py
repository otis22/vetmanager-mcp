"""Этап 293 — диапазон дат означает сутки целиком, а не полночь.

Отчёт #61 (03.09.2026): запрос счетов за один день через `date_from` и `date_to`
с одной датой возвращает `totalCount=0`, хотя счета за этот день существуют.
`invoice.create_date` — `timestamp`, а фильтр строился как
`create_date <= '2026-09-02'`, то есть сравнивался с полуночью.

Проверено на живом стенде 04.09.2026: диапазон 02.09→02.09 дал 0, диапазон
02.09→03.09 дал 27, и первая же строка — счёт с `create_date` 02.09 11:17:42.
То есть теряется не только однодневный запрос: **любой** диапазон молча
отбрасывает свой последний день.

Тесты смотрят на фактический запрос к Ветменеджеру, а не на внутреннее
состояние: значение границы и есть то, что ломалось.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _filters_from_call(call) -> list[dict]:
    query = parse_qs(urlparse(str(call.request.url)).query)
    assert "filter" in query, f"no filter param in {call.request.url}"
    return json.loads(query["filter"][0])


def _bounds(route, prop: str) -> dict[str, str]:
    return {
        f["operator"]: f["value"]
        for f in _filters_from_call(route.calls[0])
        if f["property"] == prop
    }


@pytest.mark.asyncio
@respx.mock
async def test_single_day_invoice_range_covers_the_whole_day() -> None:
    """Главный случай отчёта #61."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_invoices", {"date_from": "2026-09-02", "date_to": "2026-09-02"}
        )

    bounds = _bounds(route, "create_date")
    assert bounds[">="] == "2026-09-02 00:00:00"
    assert bounds["<"] == "2026-09-03 00:00:00"
    assert "<=" not in bounds, "верхняя граница осталась включающей по голой дате"


@pytest.mark.asyncio
@respx.mock
async def test_multi_day_invoice_range_keeps_its_last_day() -> None:
    """Незаметное следствие: последний день диапазона."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_invoices", {"date_from": "2026-08-01", "date_to": "2026-08-31"}
        )

    bounds = _bounds(route, "create_date")
    assert bounds[">="] == "2026-08-01 00:00:00"
    assert bounds["<"] == "2026-09-01 00:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_month_boundary_rolls_over_correctly() -> None:
    """Граница месяца: следующий день после 31-го — первое число, а не 32-е."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_invoices", {"date_from": "2026-12-31", "date_to": "2026-12-31"}
        )

    bounds = _bounds(route, "create_date")
    assert bounds["<"] == "2027-01-01 00:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_only_lower_bound_still_works() -> None:
    """Одна граница без второй — обычный случай «с такого-то числа»."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_invoices", {"date_from": "2026-09-01"})

    bounds = _bounds(route, "create_date")
    assert bounds == {">=": "2026-09-01 00:00:00"}


@pytest.mark.asyncio
@respx.mock
async def test_invoice_date_bounds_are_untouched() -> None:
    """Родственная пара в том же инструменте была верна и остаётся верной."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_invoices",
            {"invoice_date_from": "2026-09-02", "invoice_date_to": "2026-09-02"},
        )

    bounds = _bounds(route, "invoice_date")
    assert bounds[">="] == "2026-09-02 00:00:00"
    assert bounds["<"] == "2026-09-03 00:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_single_day_debtor_window_covers_the_whole_day() -> None:
    """Тот же класс в `get_debtors`: `client.last_visit_date` — тоже timestamp."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "client": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_debtors",
            {"last_visit_date_from": "2026-09-02", "last_visit_date_to": "2026-09-02"},
        )

    bounds = _bounds(route, "last_visit_date")
    assert bounds[">="] == "2026-09-02 00:00:00"
    assert bounds["<"] == "2026-09-03 00:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_inverted_debtor_window_is_still_rejected() -> None:
    """Проверка порядка границ не должна пострадать от смены их формата."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "client": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_debtors",
                {
                    "last_visit_date_from": "2026-09-03",
                    "last_visit_date_to": "2026-09-02",
                },
            )

    assert "last_visit_date_from" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_inactive_client_window_keeps_its_newest_day() -> None:
    """Окно неактивных клиентов: верхняя граница тоже теряла день.

    Здесь границу считает код, а не пользователь, поэтому ошибка не видна
    вовсе — клиент, заходивший в день отсечки, просто не попадал в список.
    """
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "client": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_clients", {"months_min": 6, "months_max": 12})

    bounds = _bounds(route, "last_visit_date")
    assert bounds[">="].endswith(" 00:00:00")
    assert "<" in bounds, "верхняя граница окна осталась включающей по голой дате"
    assert bounds["<"].endswith(" 00:00:00")
    upper = date.fromisoformat(bounds["<"].split(" ")[0])
    lower = date.fromisoformat(bounds[">="].split(" ")[0])
    assert upper > lower
    # Верхняя граница — начало дня, следующего за днём отсечки: сам день
    # отсечки должен входить в окно целиком.
    assert upper - lower > timedelta(days=1)

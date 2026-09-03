"""Этап 286 — выручка определена: `amount` счетов со статусом `exec`.

Отчёт #49 был не об ошибке подсчёта, а об отсутствии определения. Инструмент
считал по умолчанию кассу (`received`) — сумму exec-платежей, куда попадают
технические строки перераспределения, — и расходился с проверенным отчётом
клиники. Режим, отвечающий на нужный вопрос, в инструменте уже был, но дефолт
вёл в другой, а описание не говорило, какой из трёх воспроизводит отчёт клиники.

Решение владельца 03.09.2026: выручка — `invoice.amount` со статусом `exec`.
Здесь это записано так, чтобы переопределить его нельзя было молча.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
import respx

from server import mcp
from tests.test_revenue_summary import (
    BASE,
    _filters_from_call,
    bearer_runtime_patch,
    billing_mock,
)
from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS


@pytest.mark.asyncio
@respx.mock
async def test_default_mode_answers_the_revenue_question() -> None:
    """Без явного mode инструмент обязан отвечать про выручку, а не про кассу."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "invoice": [
                        {
                            "id": 1,
                            "amount": "1000.00",
                            "paid_amount": "400.00",
                            "status": "exec",
                            "invoice_date": "2026-03-02 10:00:00",
                        }
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_revenue_summary",
            {"date_from": "2026-03-01", "date_to": "2026-03-31"},
        )

    data = result.structured_content
    assert data["mode"] == "invoiced"
    assert data["amount_field"] == "amount"
    assert data["total_amount"] == "1000.00"

    filters = _filters_from_call(route.calls[0])
    assert ("status", "=", "exec") in {
        (f["property"], f["operator"], f["value"]) for f in filters
    }


def test_the_default_is_written_in_the_signature_too() -> None:
    """Дефолт, живущий только в вызове, расходится с кодом при первой правке.

    Разбирается исходник, а не объект FastMCP: инструмент объявлен замыканием
    внутри `register`, а внутренности фреймворка — не контракт.
    """
    source = Path(__file__).resolve().parents[1] / "tools" / "invoice.py"
    tree = ast.parse(source.read_text())
    defaults: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_revenue_summary":
            args = node.args.args
            for arg, default in zip(args[len(args) - len(node.args.defaults):], node.args.defaults):
                if isinstance(default, ast.Constant):
                    defaults[arg.arg] = default.value

    assert defaults.get("mode") == "invoiced"


def test_description_names_the_definition_out_loud() -> None:
    """Модель выбирает режим по описанию. Пока определение не названо словами,
    она берёт дефолт и получает не то число, о чём и был отчёт #49.

    Проверяются целые формулировки, а не подстроки: первая версия этого теста
    была зелёной потому, что «exec» нашёлся внутри слова «executed».
    """
    description = SPECIAL_TOOL_DESCRIPTIONS["get_revenue_summary"]

    assert "invoice.amount" in description
    assert "status='exec'" in description
    assert "cash register" in description

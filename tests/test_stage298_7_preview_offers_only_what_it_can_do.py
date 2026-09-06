"""Этап 298.7 — превью не предлагает вариант, который само же отклонит.

Найдено 06.09.2026 первым живым прогоном инструмента сквозь MCP. Превью выдаёт
групповой вариант с готовым вызовом `confirm=true`, но число **строк** у него не
считает — в ответе стоит только число товаров. На группе 66 стенда `devtr6` это
57 товаров и 112 пишущихся строк, и предел в 50 строк отклоняет ровно тот вызов,
который превью предложило. Для `row` и `good` строки считаются, для `group` —
нет.

Это расходится с собственным критерием приёмки этапа 298 («перечень вариантов
`row` / `good` / `group` **с числом затрагиваемых строк у каждого**»), и
расхождение держал зелёный тест: он проверял `variants["group"]["goods"] == 2`,
то есть закреплял единицу измерения «товары» там, где предел считает строки.

Считать строки дорого только на первый взгляд: апстрим принимает оператор `IN`
списком, и одного запроса с `limit=1` хватает, чтобы узнать `totalCount`.
Проверено на `devtr6` 06.09.2026: 114 строк всего, 2 из них `increase`, 112
пишущихся — ровно то число, которым инструмент и отказывал.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"

_ROW = {
    "id": 38, "good_id": 34, "price": "2100.0000000000", "coefficient": 1,
    "unit_sale_id": 0, "min_price": "0.0000000000", "max_price": "0.0000000000",
    "status": "active", "clinic_id": 1, "markup": "0.0000000000",
    "price_formation": "fixed",
}
_GOOD = {"id": 34, "title": "Первичный приём врача", "group_id": 72}


def _filters_of(request: httpx.Request) -> list[dict]:
    raw = request.url.params.get("filter")
    return json.loads(raw) if raw else []


def _clause(request: httpx.Request, prop: str) -> dict | None:
    return next((c for c in _filters_of(request) if c.get("property") == prop), None)


def _mocks(*, group_goods: int, group_rows: int, derived_rows: int = 0):
    """Стенд с группой заданного размера.

    Число строк группы задаётся отдельно от числа товаров: именно их
    расхождение и делает подсчёт по товарам негодным для проверки предела.
    """
    respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=httpx.Response(200, json={"data": {"goodSaleParam": dict(_ROW)}})
    )
    respx.get(f"{BASE}/rest/api/good/34").mock(
        return_value=httpx.Response(200, json={"data": {"good": dict(_GOOD)}})
    )

    goods = [dict(_GOOD, id=34 + i) for i in range(group_goods)]
    respx.get(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(200, json={"data": {"good": goods, "totalCount": len(goods)}})
    )

    seen: list[httpx.Request] = []

    def _rows(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        good_clause = _clause(request, "good_id")
        formation = _clause(request, "price_formation")
        is_group_query = bool(good_clause) and str(good_clause.get("operator", "")).upper() == "IN"
        if is_group_query:
            if formation and formation.get("value") == "increase":
                total = derived_rows
            else:
                total = group_rows
            rows = [dict(_ROW, id=1000 + i, good_id=34) for i in range(min(total, 100))]
            return httpx.Response(200, json={"data": {"goodSaleParam": rows, "totalCount": total}})
        # Строки одного товара — вариант `good`.
        return httpx.Response(200, json={"data": {"goodSaleParam": [dict(_ROW)], "totalCount": 1}})

    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(side_effect=_rows)
    return seen


async def _call(**kwargs):
    headers_patch, runtime_patch = patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="mock-token"
    )
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_good_sale_price", kwargs)
    return result.structured_content if hasattr(result, "structured_content") else result


def _group(answer: dict) -> dict:
    return next(v for v in answer["variants"] if v["scope"] == "group")


@pytest.mark.asyncio
@respx.mock
async def test_group_variant_reports_rows_not_only_goods() -> None:
    """Предел считает строки — значит и вариант обязан называть строки."""
    _mocks(group_goods=8, group_rows=16, derived_rows=1)

    answer = await _call(sale_param_id=38, change_percent=10)
    group = _group(answer)

    assert group["goods"] == 8
    assert group["rows"] == 16, "число строк группы должно быть в ответе"
    assert group["writable_rows"] == 15, "строка с наценкой не пишется и в счёт не идёт"


@pytest.mark.asyncio
@respx.mock
async def test_variant_over_the_limit_is_not_offered_as_a_ready_call() -> None:
    """Главный случай: 57 товаров и 112 строк на `devtr6` — вызов отклонялся."""
    _mocks(group_goods=57, group_rows=114, derived_rows=2)

    answer = await _call(sale_param_id=38, change_percent=10)
    group = _group(answer)

    assert group["writable_rows"] == 112
    assert group["exceeds_limit"] is True
    assert group["call"] is None, "готовый вызов, который будет отклонён, хуже его отсутствия"
    assert "50" in group["note"] and "112" in group["note"], (
        "отказ должен называть и предел, и фактическое число строк"
    )


@pytest.mark.asyncio
@respx.mock
async def test_variant_within_the_limit_is_still_offered() -> None:
    """Проверка предела не должна превратиться в запрет группового варианта."""
    _mocks(group_goods=8, group_rows=16, derived_rows=1)

    group = _group(await _call(sale_param_id=38, change_percent=10))

    assert group["exceeds_limit"] is False
    assert group["call"]["scope"] == "group"
    assert group["call"]["confirm"] is True


@pytest.mark.asyncio
@respx.mock
async def test_row_and_good_variants_also_say_whether_they_fit() -> None:
    """Признак один для всех вариантов: иначе читающий гадает, где он значим."""
    _mocks(group_goods=8, group_rows=16)

    answer = await _call(sale_param_id=38, change_percent=10)

    for variant in answer["variants"]:
        assert "exceeds_limit" in variant, f"вариант {variant['scope']} без признака"
        assert "writable_rows" in variant


@pytest.mark.asyncio
@respx.mock
async def test_group_rows_are_counted_by_one_bulk_query_not_one_per_good() -> None:
    """57 запросов ради одного числа сделали бы превью дороже самой записи."""
    seen = _mocks(group_goods=57, group_rows=114, derived_rows=2)

    await _call(sale_param_id=38, change_percent=10)

    bulk = [r for r in seen if (_clause(r, "good_id") or {}).get("operator", "").upper() == "IN"]
    assert bulk, "подсчёта не было вовсе — проверка прошла бы и на пустом месте"
    assert len(bulk) <= 2, f"на подсчёт ушло {len(bulk)} запросов вместо двух"
    assert all(r.url.params.get("limit") == "1" for r in bulk), (
        "для счёта нужен только totalCount, строки тянуть незачем"
    )


@pytest.mark.asyncio
@respx.mock
async def test_bulk_filter_passes_a_list_never_a_comma_string() -> None:
    """Апстрим принимает `IN` списком; строкой через запятую он на `devtr6`
    молча вернул 2 записи из 114 — не отказ, а неверное число."""
    seen = _mocks(group_goods=57, group_rows=114, derived_rows=2)

    await _call(sale_param_id=38, change_percent=10)

    checked = 0
    for request in seen:
        clause = _clause(request, "good_id")
        if clause and str(clause.get("operator", "")).upper() == "IN":
            assert isinstance(clause["value"], list), "значение IN должно быть списком"
            checked += 1
    assert checked, "ни одного запроса с IN — проверять было нечего"


@pytest.mark.asyncio
@respx.mock
async def test_good_without_a_group_asks_for_nothing(monkeypatch) -> None:
    """Пустой список в `IN` апстрим отдаёт 500 (проверено на `devtr6`), поэтому
    запроса быть не должно вовсе."""
    seen = _mocks(group_goods=0, group_rows=0)
    respx.get(f"{BASE}/rest/api/good/34").mock(
        return_value=httpx.Response(200, json={"data": {"good": dict(_GOOD, group_id=0)}})
    )

    group = _group(await _call(sale_param_id=38, change_percent=10))

    assert group["rows"] == 0
    assert group["call"] is None
    assert not [r for r in seen if (_clause(r, "good_id") or {}).get("operator", "").upper() == "IN"]


# --- Findings внешнего ревью 06.09.2026 ---------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_count_without_a_trustworthy_total_does_not_claim_the_variant_fits() -> None:
    """Finding ревью (medium). Счёт идёт запросом с `limit=1`: если апстрим не
    вернул `totalCount`, число строк в ответе равно единице — и вариант на 112
    строк выглядел бы проходящим. Не знать и знать «одна строка» — разные вещи.
    """
    _mocks(group_goods=57, group_rows=114, derived_rows=2)
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(
        side_effect=lambda request: httpx.Response(
            200, json={"data": {"goodSaleParam": [dict(_ROW)]}}  # без totalCount
        )
    )

    group = _group(await _call(sale_param_id=38, change_percent=10))

    assert group["rows"] is None, "неизвестное число не притворяется числом"
    assert group["exceeds_limit"] is True
    assert group["call"] is None
    assert "totalCount" in group["note"] or "неизвест" in group["note"].lower()


@pytest.mark.asyncio
@respx.mock
async def test_writing_one_row_does_not_depend_on_counting_the_group() -> None:
    """Finding ревью (medium). Превью считает группу — записи это не нужно.
    Пока счёт стоял до проверки `confirm`, запись одной строки падала бы вместе
    с любым отказом на групповом запросе, которого она не использует.
    """
    seen = _mocks(group_goods=57, group_rows=114, derived_rows=2)
    respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=httpx.Response(200, json={"data": {"goodSaleParam": dict(_ROW, price="2310.0000000000")}})
    )

    answer = await _call(sale_param_id=38, change_percent=10, scope="row", confirm=True)

    assert answer["applied"] is True
    bulk = [r for r in seen if (_clause(r, "good_id") or {}).get("operator", "").upper() == "IN"]
    assert not bulk, f"запись одной строки сделала {len(bulk)} групповых запросов"


@pytest.mark.asyncio
@respx.mock
async def test_group_call_is_absent_when_the_percent_is_not_known_yet() -> None:
    """Finding второго прогона ревью (medium). Групповая переоценка идёт только
    процентом. Если спросили абсолютной ценой, готового вызова у группы быть не
    может: `change_percent="укажите процент"` — записка, а не вызов, и повтор
    падает на валидации типа. Непустой `call` обязан означать «выполнимо».
    """
    _mocks(group_goods=8, group_rows=16, derived_rows=1)

    group = _group(await _call(sale_param_id=38, new_price=2500))

    assert group["exceeds_limit"] is False, "по объёму вариант проходит"
    assert group["call"] is None
    assert "change_percent" in group["note"]

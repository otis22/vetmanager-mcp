"""Этап 298 — цена продажи меняется только с подтверждением.

Решение владельца 05.09.2026: делать, но с подтверждением, и предлагать варианты
с учётом клиник и групп товаров.

Почему подтверждение обязательно, а не «как у других update-инструментов»:
цену сразу видят клиенты клиники, а «цена товара» — не одно поле. В таблице
`good_sale_param` у `good_id` неуникальный индекс: строк несколько, по клиникам
и единицам продажи. Плюс `price_formation` = `fixed` / `increase`: у второй цена
выводится из наценки, и запись `price` туда выглядит выполненной, а результата
не даёт — тот же класс, что этап 296.

Главная проверка здесь — не текст ответа, а **отсутствие запроса на запись**
без подтверждения.
"""

from __future__ import annotations

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
_SIBLING = dict(_ROW, id=39, clinic_id=2, price="2300.0000000000")
_DERIVED = dict(_ROW, id=40, clinic_id=3, price_formation="increase", markup="30.0")
_GOOD = {"id": 34, "title": "Первичный приём врача", "group_id": 72}


def _mocks(rows=None, goods=None, bounded=False):
    respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    row = dict(_ROW)
    if bounded:
        # Проценты, а не рубли: −10% и +20% от цены.
        row = dict(row, min_price="10.0000000000", max_price="20.0000000000")
    # Мок отражает запись: до PUT отдаёт старую цену, после — новую. Иначе
    # проверка «стало читается заново» проходила бы и на эхе запроса.
    state = {"price": row["price"]}

    def _read_row(_request):
        return httpx.Response(200, json={"data": {"goodSaleParam": dict(row, price=state["price"])}})

    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(side_effect=_read_row)
    respx.get(f"{BASE}/rest/api/goodSaleParam/40").mock(
        return_value=httpx.Response(200, json={"data": {"goodSaleParam": dict(_DERIVED)}})
    )
    respx.get(f"{BASE}/rest/api/good/34").mock(
        return_value=httpx.Response(200, json={"data": {"good": dict(_GOOD)}})
    )
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(
        return_value=httpx.Response(200, json={"data": {
            "goodSaleParam": rows if rows is not None else [row, _SIBLING, _DERIVED],
            "totalCount": 3,
        }})
    )
    respx.get(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(200, json={"data": {
            "good": goods if goods is not None else [_GOOD, {"id": 35, "group_id": 72}],
            "totalCount": 2,
        }})
    )
    def _write_row(request):
        import json as _json
        body = _json.loads(request.content or b"{}")
        state["price"] = f'{float(body.get("price", state["price"])):.10f}'
        return httpx.Response(200, json={"data": {"goodSaleParam": dict(row, price=state["price"])}})

    return respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(side_effect=_write_row)


async def _call(**kwargs):
    headers_patch, runtime_patch = patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="mock-token"
    )
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_good_sale_price", kwargs)
    return result.structured_content if hasattr(result, "structured_content") else result


@pytest.mark.asyncio
@respx.mock
async def test_without_confirmation_nothing_is_written() -> None:
    """Главная проверка: смотрим на фактические запросы, а не на текст ответа."""
    write = _mocks()

    answer = await _call(sale_param_id=38, new_price=2500)

    assert write.call_count == 0, "превью отправило запись"
    assert answer["applied"] is False
    assert answer["current_price"] == "2100.0000000000"
    assert answer["new_price"] == "2500.00"


@pytest.mark.asyncio
@respx.mock
async def test_preview_offers_variants_with_row_counts() -> None:
    """Уточнение владельца: инструмент предлагает варианты по клиникам и группам."""
    _mocks()

    answer = await _call(sale_param_id=38, new_price=2500)
    variants = {v["scope"]: v for v in answer["variants"]}

    assert set(variants) == {"row", "good", "group"}
    assert variants["row"]["rows"] == 1
    assert variants["good"]["rows"] == 3, "у товара три строки цены"
    assert variants["group"]["goods"] == 2
    for variant in variants.values():
        assert "call" in variant, "вариант без готового вызова бесполезен"


@pytest.mark.asyncio
@respx.mock
async def test_derived_price_row_is_refused() -> None:
    """`increase` — цена выводится из наценки; запись выглядела бы выполненной."""
    _mocks()

    with pytest.raises(Exception) as exc_info:
        await _call(sale_param_id=40, new_price=2500)

    message = str(exc_info.value)
    assert "increase" in message or "наценк" in message


@pytest.mark.asyncio
@respx.mock
async def test_min_and_max_price_are_percents_and_do_not_block_the_write() -> None:
    """Внешнее ревью 05.09.2026, finding high — принят.

    Первая версия сравнивала новую цену с `min_price`/`max_price` как с
    абсолютными границами и отклоняла запись. В апстриме это **проценты**:

        $minPrice = $price - $price * $min_price / 100;
        $maxPrice = $price + $price * $max_price / 100;

    (`GoodController.php`, плюс миграция 2014 года
    `m140311_081943_update_good_sets_max_min_to_percents`.)

    Коридор считается **от текущей цены**, то есть это допустимая скидка и
    наценка при продаже, а не ограничение на то, какую цену можно поставить.
    Проверку не чинили, а убрали: она отвечала не на тот вопрос. Вместо неё
    превью показывает получившийся коридор — последствие видно, запрета нет.
    """
    _mocks(bounded=True)

    answer = await _call(sale_param_id=38, new_price=9999)

    assert answer["applied"] is False
    band = answer["sale_band"]
    # min_price=10 → нижняя граница 9999 - 10%; max_price=20 → верхняя +20%.
    assert band["min"] == "8999.10"
    assert band["max"] == "11998.80"
    assert "процент" in band["note"] or "percent" in band["note"]


@pytest.mark.asyncio
@respx.mock
async def test_variant_call_can_be_repeated_verbatim() -> None:
    """Внешнее ревью, finding medium — принят.

    Превью обещало «готовый вызов», но не клало в него саму величину: повтор
    буквально падал на «Pass exactly one of new_price or change_percent».
    """
    _mocks()

    answer = await _call(sale_param_id=38, new_price=2500)
    for variant in answer["variants"]:
        call = variant["call"]
        if variant["scope"] == "group":
            assert "change_percent" in call
        else:
            assert call.get("new_price") == 2500.0 or call.get("change_percent")


@pytest.mark.asyncio
@respx.mock
async def test_mass_variant_refuses_instead_of_silently_truncating() -> None:
    """Внешнее ревью, finding high — принят.

    Выборка строк шла одной страницей по 100 и игнорировала `totalCount`:
    на большой группе превью было неполным, а обновление — частичным.
    Молчаливая неполнота на записи цен опаснее отказа.
    """
    _mocks()
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(
        return_value=httpx.Response(200, json={"data": {
            "goodSaleParam": [dict(_ROW)], "totalCount": 4000,
        }})
    )

    with pytest.raises(Exception) as exc_info:
        await _call(sale_param_id=38, change_percent=5, scope="good", confirm=True)

    assert "4000" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("bad", [float("inf"), float("nan")])
async def test_non_finite_money_is_a_refusal_not_a_crash(bad: float) -> None:
    """Внешнее ревью, finding medium — принят."""
    _mocks()

    with pytest.raises(Exception) as exc_info:
        await _call(sale_param_id=38, new_price=bad)

    assert "finite" in str(exc_info.value) or "число" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_absolute_price_for_a_group_is_refused() -> None:
    """Одна цена всем товарам группы — почти наверняка не то, что имелось в виду."""
    _mocks()

    with pytest.raises(Exception) as exc_info:
        await _call(sale_param_id=38, new_price=2500, scope="group", confirm=True)

    assert "change_percent" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_percent_change_is_computed_from_the_current_price() -> None:
    _mocks()

    answer = await _call(sale_param_id=38, change_percent=10)

    assert answer["new_price"] == "2310.00"
    assert answer["applied"] is False


@pytest.mark.asyncio
@respx.mock
async def test_confirmation_writes_and_reports_before_and_after() -> None:
    write = _mocks()

    answer = await _call(sale_param_id=38, new_price=2500, confirm=True)

    assert write.call_count == 1
    assert answer["applied"] is True
    assert answer["before"] == "2100.0000000000"
    assert answer["after"] == "2500.0000000000", "«стало» читается заново, а не из эха запроса"


@pytest.mark.asyncio
@respx.mock
async def test_neither_price_nor_percent_is_refused() -> None:
    _mocks()

    with pytest.raises(Exception):
        await _call(sale_param_id=38)


@pytest.mark.asyncio
@respx.mock
async def test_both_price_and_percent_is_refused() -> None:
    """Два способа задать одну величину — заявка на молчаливый выбор за человека."""
    _mocks()

    with pytest.raises(Exception):
        await _call(sale_param_id=38, new_price=2500, change_percent=10)

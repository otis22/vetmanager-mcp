import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import SCOPE_CLIENTS_READ, SCOPE_INVENTORY_READ, required_scope_for_request


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch(*, scopes=(SCOPE_INVENTORY_READ,)):
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        scopes=scopes,
    )


def _structured(result) -> dict:
    return result.structured_content


def _params(route) -> dict:
    return dict(route.calls.last.request.url.params)


def _products_payload(rows: list[dict], *, total: int | None = None) -> dict:
    data = {"good": rows}
    if total is not None:
        data["totalCount"] = total
    return {"success": True, "message": "", "data": data}


def _goodtag_payload(rows: list[dict]) -> dict:
    return {"success": True, "message": "", "data": {"goodTag": rows, "totalCount": len(rows)}}


def _combination_row(tag_id: int | None, *, title: str = "Combo", row_id: str | None = None) -> dict:
    if row_id is None:
        row_id = f"-{tag_id}"
    row = {
        "id": row_id,
        "name": title,
        "good_group": "GoodsSets",
        "price": "200.00",
        "default_price": "200.00",
        "sale_param_id": 12,
    }
    if tag_id is not None:
        row["tag_id"] = tag_id
    return row


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_returns_plain_good_without_goodtag_enrichment():
    billing_mock()
    products_route = respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        return_value=httpx.Response(
            200,
            json=_products_payload(
                [
                    {
                        "id": "494_968_0",
                        "name": "Consultation",
                        "good_group": "Services",
                        "price": "1500.00",
                        "default_price": "1500.00",
                        "sale_param_id": 968,
                    }
                ]
            ),
        )
    )
    goodtag_route = respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(200, json=_goodtag_payload([]))
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "consult", "clinic_id": 1, "limit": 20},
        )

    payload = _structured(result)["data"]
    assert products_route.call_count == 1
    assert goodtag_route.call_count == 0
    row = payload["items"][0]
    assert row["invoice_good_id"] == "494_968_0"
    assert row["title"] == "Consultation"
    assert row["is_combination"] is False
    assert row["combination_tag_id"] is None
    assert row["is_template"] is False
    assert "combination" not in row
    assert payload["metadata"]["warnings"] == []


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_returns_ordinary_combination_and_bulk_enriches():
    billing_mock()
    products_route = respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        return_value=httpx.Response(
            200,
            json=_products_payload([_combination_row(None, title="ggg", row_id="-2")]),
        )
    )
    goodtag_route = respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(
            200,
            json=_goodtag_payload(
                [
                    {
                        "id": 2,
                        "title": "ggg",
                        "is_template": "0",
                        "positions": [{"tag_id": 2, "quantity": "1.000", "sale_param_id": 12}],
                    }
                ]
            ),
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "ggg", "clinic_id": 1, "limit": 20},
        )

    payload = _structured(result)["data"]
    assert products_route.call_count == 1
    assert goodtag_route.call_count == 1
    assert _params(products_route)["limit"] == "100"
    assert _params(products_route)["offset"] == "0"
    goodtag_params = _params(goodtag_route)
    assert goodtag_params["limit"] == "1"
    assert goodtag_params["offset"] == "0"
    assert json.loads(goodtag_params["filter"]) == [
        {"property": "id", "value": [2], "operator": "IN"}
    ]
    row = payload["items"][0]
    assert row["invoice_good_id"] == "-2"
    assert row["is_combination"] is True
    assert row["combination_tag_id"] == 2
    assert row["is_template"] is False
    assert payload["metadata"]["accepted_count"] == 1
    assert payload["metadata"]["warnings"] == []


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_filters_templates_by_default_and_can_include_them():
    billing_mock()
    products_route = respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        return_value=httpx.Response(
            200,
            json=_products_payload([_combination_row(6, title="Тест1")]),
        )
    )
    goodtag_route = respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(
            200,
            json=_goodtag_payload([{"id": 6, "title": "Тест1", "is_template": 1, "positions": []}]),
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        default_result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "Тест1", "clinic_id": 1, "limit": 20},
        )
        included_result = await mcp.call_tool(
            "search_invoice_goods",
            {
                "query": "Тест1",
                "clinic_id": 1,
                "limit": 20,
                "include_template_combinations": True,
            },
        )

    assert products_route.call_count == 1
    assert goodtag_route.call_count == 1
    assert _structured(default_result)["data"]["items"] == []
    included_items = _structured(included_result)["data"]["items"]
    assert len(included_items) == 1
    assert included_items[0]["combination_tag_id"] == 6
    assert included_items[0]["is_template"] is True


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_overfetches_after_template_filtering_with_caps():
    billing_mock()
    products_route = respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        side_effect=[
            httpx.Response(
                200,
                json=_products_payload(
                    [_combination_row(6, title=f"Template {index}") for index in range(100)]
                ),
            ),
            httpx.Response(200, json=_products_payload([_combination_row(2, title="Ordinary")])),
        ]
    )
    goodtag_route = respx.get(f"{BASE}/rest/api/goodTag").mock(
        side_effect=[
            httpx.Response(200, json=_goodtag_payload([{"id": 6, "title": "Template", "is_template": "1"}])),
            httpx.Response(200, json=_goodtag_payload([{"id": 2, "title": "Ordinary", "is_template": "0"}])),
        ]
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "", "clinic_id": 1, "limit": 1},
        )

    payload = _structured(result)["data"]
    assert products_route.call_count == 2
    assert [str(call.request.url.params["offset"]) for call in products_route.calls] == ["0", "100"]
    assert payload["items"][0]["combination_tag_id"] == 2
    assert payload["metadata"]["upstream_pages_fetched"] == 2
    assert payload["metadata"]["inspected_count"] == 101
    assert payload["metadata"]["overfetch_cap_reached"] is False


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_stops_at_product_overfetch_hard_cap():
    billing_mock()
    products_route = respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        side_effect=[
            httpx.Response(
                200,
                json=_products_payload(
                    [
                        _combination_row(page + 1, title=f"Template {page}-{index}")
                        for index in range(100)
                    ]
                ),
            )
            for page in range(5)
        ]
    )
    respx.get(f"{BASE}/rest/api/goodTag").mock(
        side_effect=[
            httpx.Response(
                200,
                json=_goodtag_payload([{"id": page + 1, "title": "Template", "is_template": "1"}]),
            )
            for page in range(5)
        ]
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "", "clinic_id": 1, "limit": 1},
        )

    payload = _structured(result)["data"]
    assert payload["items"] == []
    assert products_route.call_count == 5
    assert [str(call.request.url.params["offset"]) for call in products_route.calls] == [
        "0",
        "100",
        "200",
        "300",
        "400",
    ]
    assert payload["metadata"]["upstream_pages_fetched"] == 5
    assert payload["metadata"]["inspected_count"] == 500
    assert payload["metadata"]["overfetch_cap_reached"] is True


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_caps_goodtag_enrichment_at_50_tag_ids():
    billing_mock()
    rows = [_combination_row(tag_id, title=f"Combo {tag_id}") for tag_id in range(1, 61)]
    respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        return_value=httpx.Response(200, json=_products_payload(rows))
    )
    goodtag_route = respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(
            200,
            json=_goodtag_payload(
                [
                    {"id": tag_id, "title": f"Combo {tag_id}", "is_template": "0"}
                    for tag_id in range(1, 51)
                ]
            ),
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "search_invoice_goods",
            {
                "query": "",
                "clinic_id": 1,
                "limit": 60,
                "include_template_combinations": True,
            },
        )

    payload = _structured(result)["data"]
    goodtag_params = _params(goodtag_route)
    assert goodtag_params["limit"] == "50"
    assert json.loads(goodtag_params["filter"])[0]["value"] == list(range(1, 51))
    assert len(payload["items"]) == 60
    assert payload["items"][49]["is_template"] is False
    assert payload["items"][50]["combination_tag_id"] == 51
    assert payload["items"][50]["is_template"] is None
    assert "goodTag enrichment capped at 50 tag IDs" in payload["metadata"]["warnings"][0]
    assert any("tag_id=51" in warning for warning in payload["metadata"]["warnings"])


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_goodtag_cap_is_global_across_overfetch_pages():
    billing_mock()
    products_route = respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        side_effect=[
            httpx.Response(
                200,
                json=_products_payload(
                    [_combination_row(tag_id, title=f"Page 1 Combo {tag_id}") for tag_id in range(1, 101)]
                ),
            ),
            httpx.Response(
                200,
                json=_products_payload(
                    [_combination_row(tag_id, title=f"Page 2 Combo {tag_id}") for tag_id in range(101, 201)]
                ),
            ),
            httpx.Response(200, json=_products_payload([])),
        ]
    )
    goodtag_route = respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(
            200,
            json=_goodtag_payload(
                [{"id": tag_id, "title": f"Template {tag_id}", "is_template": "1"} for tag_id in range(1, 51)]
            ),
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "", "clinic_id": 1, "limit": 1},
        )

    payload = _structured(result)["data"]
    assert payload["items"] == []
    assert products_route.call_count == 3
    assert goodtag_route.call_count == 1
    assert _params(goodtag_route)["limit"] == "50"
    assert json.loads(_params(goodtag_route)["filter"])[0]["value"] == list(range(1, 51))
    assert "goodTag enrichment capped at 50 tag IDs" in payload["metadata"]["warnings"][0]
    assert any("tag_id=101" in warning for warning in payload["metadata"]["warnings"])


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_stops_before_offset_exceeds_validator_bound():
    billing_mock()
    products_route = respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        side_effect=[
            httpx.Response(
                200,
                json=_products_payload([_combination_row(6, title=f"Template {index}") for index in range(100)]),
            ),
            httpx.Response(
                200,
                json=_products_payload([_combination_row(6, title=f"Template {index}") for index in range(100)]),
            ),
        ]
    )
    respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(200, json=_goodtag_payload([{"id": 6, "title": "Template", "is_template": "1"}]))
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "", "clinic_id": 1, "limit": 1, "offset": 9900},
        )

    payload = _structured(result)["data"]
    assert [str(call.request.url.params["offset"]) for call in products_route.calls] == ["9900", "10000"]
    assert payload["items"] == []
    assert payload["metadata"]["upstream_pages_fetched"] == 2
    assert payload["metadata"]["overfetch_cap_reached"] is True
    assert any("offset 10100" in warning for warning in payload["metadata"]["warnings"])


@pytest.mark.asyncio
@respx.mock
async def test_search_invoice_goods_fails_closed_when_goodtag_enrichment_missing():
    billing_mock()
    respx.get(f"{BASE}/rest/api/good/productsDataForInvoice").mock(
        return_value=httpx.Response(200, json=_products_payload([_combination_row(9, title="Unknown")]))
    )
    respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(200, json=_goodtag_payload([]))
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        default_result = await mcp.call_tool(
            "search_invoice_goods",
            {"query": "Unknown", "clinic_id": 1, "limit": 20},
        )
        included_result = await mcp.call_tool(
            "search_invoice_goods",
            {
                "query": "Unknown",
                "clinic_id": 1,
                "limit": 20,
                "include_template_combinations": True,
            },
        )

    default_payload = _structured(default_result)["data"]
    included_payload = _structured(included_result)["data"]
    assert default_payload["items"] == []
    assert "missing goodTag metadata" in default_payload["metadata"]["warnings"][0]
    assert included_payload["items"][0]["is_template"] is None
    assert "missing goodTag metadata" in included_payload["metadata"]["warnings"][0]


@pytest.mark.asyncio
@respx.mock
async def test_get_good_combination_returns_positions():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(
            200,
            json=_goodtag_payload(
                [
                    {
                        "id": 2,
                        "title": "ggg",
                        "is_template": "0",
                        "positions": [
                            {
                                "tag_id": 2,
                                "quantity": "2.000",
                                "sale_param_id": 12,
                                "price_formation": "fixed",
                                "good": {"id": 50, "title": "Drug"},
                                "good_sale_param": {"id": 12, "price": "100.00"},
                            }
                        ],
                    }
                ]
            ),
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_good_combination", {"tag_id": 2, "clinic_id": 1})

    payload = _structured(result)["data"]
    assert route.call_count == 1
    assert json.loads(_params(route)["filter"]) == [{"property": "id", "value": 2, "operator": "="}]
    assert payload["combination"]["id"] == 2
    assert payload["combination"]["is_template"] is False
    assert payload["combination"]["positions"][0]["good"]["title"] == "Drug"


@pytest.mark.asyncio
@respx.mock
async def test_calculate_good_combination_price_uses_server_check_product_data():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/good/checkProductData").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "good": {
                        "id": "-2",
                        "tag_id": 2,
                        "price": "200.0",
                        "amount": "400.0",
                        "qty": "2",
                    },
                    "action_is_possible": 1,
                    "allowed_quantity": 0,
                },
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "calculate_good_combination_price",
            {"tag_id": 2, "quantity": 2, "clinic_id": 1},
        )

    params = _params(route)
    assert params["good_id"] == "-2"
    assert params["tag_id"] == "2"
    assert params["qty"] == "2.0"
    assert params["clinic_id"] == "1"
    payload = _structured(result)["data"]
    assert payload["good"]["amount"] == "400.0"
    assert payload["action_is_possible"] == 1


@pytest.mark.parametrize(
    ("tool_name", "args", "upstream_path"),
    [
        (
            "search_invoice_goods",
            {"query": "x", "clinic_id": 1},
            "/rest/api/good/productsDataForInvoice",
        ),
        ("get_good_combination", {"tag_id": 2, "clinic_id": 1}, "/rest/api/goodTag"),
        (
            "calculate_good_combination_price",
            {"tag_id": 2, "quantity": 1, "clinic_id": 1},
            "/rest/api/good/checkProductData",
        ),
    ],
)
@pytest.mark.asyncio
@respx.mock
async def test_stage169_tools_require_inventory_scope_before_upstream(tool_name, args, upstream_path):
    billing_mock()
    route = respx.get(f"{BASE}{upstream_path}").mock(return_value=httpx.Response(200, json={}))

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_CLIENTS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="inventory.read"):
            await mcp.call_tool(tool_name, args)

    assert route.call_count == 0


def test_stage169_request_scope_mapping():
    assert required_scope_for_request("GET", "/rest/api/good/productsDataForInvoice") == SCOPE_INVENTORY_READ
    assert required_scope_for_request("GET", "/rest/api/good/checkProductData") == SCOPE_INVENTORY_READ
    assert required_scope_for_request("GET", "/rest/api/goodTag") == SCOPE_INVENTORY_READ

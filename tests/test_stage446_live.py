"""Read-only warehouse guidance probe on the .env test contour."""

import os
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

pytestmark = pytest.mark.real_api


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env test contour unavailable")
async def test_stage446_live_narrow_store_documents(capsys):
    headers, runtime = patch_runtime_credentials(os.environ["TEST_DOMAIN"],
                                                 os.environ["TEST_API_KEY"])
    observed = []
    original = httpx.AsyncClient.request

    async def capture(client, method, url, **kwargs):
        response = await original(client, method, url, **kwargs)
        if "/rest/api/StoreDocument" in str(url):
            observed.append((method, response.status_code))
        return response

    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        first = await mcp.call_tool("get_store_documents", {"limit": 1, "offset": 0,
            "filter": [{"property": "document_type", "value": "prihod", "operator": "="}]})
        assert not first.is_error
        docs = first.structured_content.get("data", {}).get("storeDocument") or []
        assert docs, "test contour needs one supplier receipt"
        doc = docs[0]
        month = str(doc["add_dt"])[:7]
        year, number = map(int, month.split("-"))
        next_month = f"{year + (number == 12):04d}-{number % 12 + 1:02d}-01 00:00:00"
        filtered = await mcp.call_tool("get_store_documents", {"limit": 2, "offset": 0,
            "filter": [
                {"property": "document_type", "value": "prihod", "operator": "="},
                {"property": "add_dt", "value": f"{month}-01 00:00:00", "operator": ">="},
                {"property": "add_dt", "value": next_month, "operator": "<"},
            ]})
        detail = await mcp.call_tool("get_store_document_by_id", {"doc_id": int(doc["id"])})

    assert not filtered.is_error and not detail.is_error
    month_docs = filtered.structured_content.get("data", {}).get("storeDocument") or []
    assert any(int(row["id"]) == int(doc["id"]) for row in month_docs)
    assert observed and all(method == "GET" and status == 200 for method, status in observed)
    with capsys.disabled():
        print("STAGE446_LIVE rest_calls_all_GET_200=true body=" + str({
            "first_count": len(docs),
            "month_page_count": len(month_docs),
            "detail_success": not detail.is_error,
            "accounting_date_unverified": True,
            "category_totals_unverified": True,
        }))

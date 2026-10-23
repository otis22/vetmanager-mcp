"""Guard agent navigation between stock documents and supplier payments."""

import pytest

from server import mcp


@pytest.mark.asyncio
async def test_store_document_descriptions_distinguish_stock_and_money():
    catalog = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    listing = catalog["get_store_documents"].description
    detail = catalog["get_store_document_by_id"].description

    assert "prihod" in listing and "rashod" in listing
    assert "supplier_id" in listing and "document_type" in listing
    assert "payment" in listing.lower()
    assert "not payment" in listing.lower()
    assert "not payment" in detail.lower()
    assert "history" in detail.lower()
    assert "supplier bill to pay" in listing
    filter_schema = catalog["get_store_documents"].inputSchema["properties"]["filter"]
    assert "supplier_id" in filter_schema["description"]
    assert "add_dt" in filter_schema["description"]

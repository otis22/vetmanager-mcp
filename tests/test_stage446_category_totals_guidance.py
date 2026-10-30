"""Guard warehouse guidance against invented category purchase totals."""

import pytest

from server import mcp


@pytest.mark.asyncio
async def test_store_documents_do_not_promise_category_totals():
    catalog = {tool.name: tool.to_mcp_tool().description for tool in await mcp.list_tools()}
    listing = catalog["get_store_documents"]
    detail = catalog["get_store_document_by_id"]

    assert "monthly purchase totals by goods category" in listing
    assert "do not allocate storedocument.total to categories" in listing.lower()
    assert "document_type='prihod'" in listing and "one month of add_dt" in listing
    assert "add_dt is only a list filter, not a verified purchase accounting date" in listing
    assert "current operation revision" in listing
    assert "current operation revision" in detail

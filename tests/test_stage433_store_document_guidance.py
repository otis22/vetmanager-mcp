"""Guard agent navigation between stock documents and supplier payments."""

from tool_descriptions import compose_tool_description


def test_store_document_descriptions_distinguish_stock_and_money():
    listing = compose_tool_description("get_store_documents")
    detail = compose_tool_description("get_store_document_by_id")

    assert "prihod" in listing and "rashod" in listing
    assert "supplier_id" in listing and "document_type" in listing
    assert "payment" in listing.lower()
    assert "not payment" in listing.lower()
    assert "not payment" in detail.lower()
    assert "history" in detail.lower()

"""Financial entity tools: Payment, ClosingOfInvoices, InvoiceDocument, Cassa, CassaClose."""

from fastmcp import FastMCP
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_delete
from validators import LimitParam, validate_amount


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_payments(
        limit: LimitParam = 20,
        offset: int = 0,
        client_id: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List client payments in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            client_id: Filter by client ID (0 = no filter).
        """
        return await crud_list(
            "/rest/api/payment", limit=limit, offset=offset,
            sort=sort, filters=filter, extra={"clientId": client_id},
        )

    @mcp.tool
    async def get_payment_by_id(payment_id: int) -> dict:
        """Get a payment record by its unique ID.

        Args:
            payment_id: Unique numeric ID of the payment.
        """
        return await crud_get_by_id("/rest/api/payment", payment_id)

    @mcp.tool
    async def create_payment(client_id: int, amount: float, cassa_id: int, description: str = "") -> dict:
        """Register a new payment from a client.

        Args:
            client_id: ID of the paying client.
            amount: Payment amount.
            cassa_id: ID of the cash register (cassa) receiving payment.
            description: Optional payment description or note.
        """
        validate_amount(amount)
        payload: dict = {"clientId": client_id, "amount": amount, "cassaId": cassa_id}
        if description:
            payload["description"] = description
        return await crud_create("/rest/api/payment", payload)

    @mcp.tool
    async def get_closing_of_invoices(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List invoice closing records (payments applied to invoices).

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/closingOfInvoices", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_closing_of_invoice_by_id(closing_id: int) -> dict:
        """Get an invoice closing record by its unique ID.

        Args:
            closing_id: Unique numeric ID of the closing record.
        """
        return await crud_get_by_id("/rest/api/closingOfInvoices", closing_id)

    @mcp.tool
    async def get_invoice_documents(
        invoice_id: int,
        limit: LimitParam = 50,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List line items (goods/services) within a specific invoice.

        Args:
            invoice_id: ID of the parent invoice.
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/invoiceDocument", limit=limit, offset=offset,
            sort=sort, filters=filter, extra={"invoiceId": invoice_id},
        )

    @mcp.tool
    async def get_invoice_document_by_id(doc_id: int) -> dict:
        """Get a single invoice line item by its unique ID.

        Args:
            doc_id: Unique numeric ID of the invoice document.
        """
        return await crud_get_by_id("/rest/api/invoiceDocument", doc_id)

    @mcp.tool
    async def add_invoice_document(invoice_id: int, good_id: int, quantity: float, price: float) -> dict:
        """Add a line item (good or service) to an existing invoice.

        Args:
            invoice_id: ID of the invoice to add the item to.
            good_id: ID of the good or service.
            quantity: Quantity of the item.
            price: Price per unit.
        """
        return await crud_create(
            "/rest/api/invoiceDocument",
            {"invoiceId": invoice_id, "goodId": good_id, "quantity": quantity, "price": price},
        )

    @mcp.tool
    async def delete_invoice_document(doc_id: int) -> dict:
        """Delete an invoice line item by its ID.

        WARNING: This permanently removes the line item from the invoice.

        Args:
            doc_id: ID of the invoice document (line item) to delete.
        """
        return await crud_delete("/rest/api/invoiceDocument", doc_id)

    @mcp.tool
    async def get_cassas(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List cash registers (cassas) in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/cassa", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_cassa_by_id(cassa_id: int) -> dict:
        """Get a cash register by its unique ID.

        Args:
            cassa_id: Unique numeric ID of the cash register.
        """
        return await crud_get_by_id("/rest/api/cassa", cassa_id)

    @mcp.tool
    async def get_cassa_closes(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List cash register closing records.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/cassaclose", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_cassa_close_by_id(close_id: int) -> dict:
        """Get a cash register closing record by its unique ID.

        Args:
            close_id: Unique numeric ID of the closing record.
        """
        return await crud_get_by_id("/rest/api/cassaclose", close_id)

"""Financial entity tools: Payment, ClosingOfInvoices, InvoiceDocument, Cassa, CassaClose."""

from fastmcp import FastMCP
from validators import LimitParam, build_list_query_params, validate_amount
from vetmanager_client import VetmanagerClient


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
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            client_id: Filter by client ID (0 = no filter).
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"clientId": client_id},
        )
        return await vc.get("/rest/api/payment", params=params)

    @mcp.tool
    async def get_payment_by_id(payment_id: int) -> dict:
        """Get a payment record by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            payment_id: Unique numeric ID of the payment.
        """
        return await VetmanagerClient().get(f"/rest/api/payment/{payment_id}")

    @mcp.tool
    async def create_payment(client_id: int, amount: float, cassa_id: int, description: str = "") -> dict:
        """Register a new payment from a client.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: ID of the paying client.
            amount: Payment amount.
            cassa_id: ID of the cash register (cassa) receiving payment.
            description: Optional payment description or note.
        """
        vc = VetmanagerClient()
        validate_amount(amount)
        payload: dict = {"clientId": client_id, "amount": amount, "cassaId": cassa_id}
        if description:
            payload["description"] = description
        return await vc.post("/rest/api/payment", json=payload)

    @mcp.tool
    async def get_closing_of_invoices(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List invoice closing records (payments applied to invoices).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/closingOfInvoices", params=params)

    @mcp.tool
    async def get_closing_of_invoice_by_id(closing_id: int) -> dict:
        """Get an invoice closing record by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            closing_id: Unique numeric ID of the closing record.
        """
        return await VetmanagerClient().get(f"/rest/api/closingOfInvoices/{closing_id}")

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
            domain: Clinic subdomain.
            api_key: REST API key.
            invoice_id: ID of the parent invoice.
            limit: Max records to return.
            offset: Pagination offset.
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"invoiceId": invoice_id},
        )
        return await vc.get("/rest/api/invoiceDocument", params=params)

    @mcp.tool
    async def get_invoice_document_by_id(doc_id: int) -> dict:
        """Get a single invoice line item by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            doc_id: Unique numeric ID of the invoice document.
        """
        return await VetmanagerClient().get(f"/rest/api/invoiceDocument/{doc_id}")

    @mcp.tool
    async def add_invoice_document(invoice_id: int, good_id: int, quantity: float, price: float) -> dict:
        """Add a line item (good or service) to an existing invoice.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            invoice_id: ID of the invoice to add the item to.
            good_id: ID of the good or service.
            quantity: Quantity of the item.
            price: Price per unit.
        """
        vc = VetmanagerClient()
        return await vc.post("/rest/api/invoiceDocument", json={"invoiceId": invoice_id, "goodId": good_id, "quantity": quantity, "price": price})

    @mcp.tool
    async def get_cassas(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List cash registers (cassas) in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/cassa", params=params)

    @mcp.tool
    async def get_cassa_by_id(cassa_id: int) -> dict:
        """Get a cash register by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            cassa_id: Unique numeric ID of the cash register.
        """
        return await VetmanagerClient().get(f"/rest/api/cassa/{cassa_id}")

    @mcp.tool
    async def get_cassa_closes(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List cash register closing records.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/cassaclose", params=params)

    @mcp.tool
    async def get_cassa_close_by_id(close_id: int) -> dict:
        """Get a cash register closing record by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            close_id: Unique numeric ID of the closing record.
        """
        return await VetmanagerClient().get(f"/rest/api/cassaclose/{close_id}")

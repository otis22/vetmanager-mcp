from fastmcp import FastMCP

from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_invoices(
        domain: str,
        api_key: str,
        limit: int = 20,
        offset: int = 0,
        client_id: int = 0,
    ) -> dict:
        """List invoices in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            client_id: Filter by client ID (0 = no filter).
        """
        vc = VetmanagerClient(domain, api_key)
        params: dict = {"limit": limit, "offset": offset}
        if client_id:
            params["client_id"] = client_id
        return await vc.get("/rest/api/invoice", params=params)

    @mcp.tool
    async def get_invoice_by_id(
        domain: str,
        api_key: str,
        invoice_id: int,
    ) -> dict:
        """Get a specific invoice by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            invoice_id: Unique numeric ID of the invoice.
        """
        vc = VetmanagerClient(domain, api_key)
        return await vc.get(f"/rest/api/invoice/{invoice_id}")

    @mcp.tool
    async def create_invoice(
        domain: str,
        api_key: str,
        client_id: int,
        pet_id: int,
        description: str = "",
    ) -> dict:
        """Create a new invoice for a client/pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: ID of the client being invoiced.
            pet_id: ID of the pet the invoice is for.
            description: Optional description for the invoice.
        """
        vc = VetmanagerClient(domain, api_key)
        payload: dict = {"client_id": client_id, "pet_id": pet_id}
        if description:
            payload["description"] = description
        return await vc.post("/rest/api/invoice", json=payload)

from fastmcp import FastMCP

from validators import build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clients(
        limit: int = 20,
        offset: int = 0,
        name: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List clients of the clinic.

        Args:
            domain: Clinic subdomain (e.g. 'myclinic').
            api_key: REST API key from Vetmanager Settings → Integration → Rest API.
            limit: Max number of records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            name: Filter by client name (partial match).
        """
        client = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"name": name},
        )
        return await client.get("/rest/api/client", params=params)

    @mcp.tool
    async def get_client_by_id(
        client_id: int,
    ) -> dict:
        """Get a clinic client by their unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: Unique numeric ID of the client.
        """
        client = VetmanagerClient()
        return await client.get(f"/rest/api/client/{client_id}")

    @mcp.tool
    async def create_client(
        first_name: str,
        last_name: str,
        phone: str = "",
        email: str = "",
    ) -> dict:
        """Create a new client in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            first_name: Client's first name.
            last_name: Client's last name.
            phone: Contact phone number.
            email: Contact email address.
        """
        client = VetmanagerClient()
        payload: dict = {"firstName": first_name, "lastName": last_name}
        if phone:
            payload["phone"] = phone
        if email:
            payload["email"] = email
        return await client.post("/rest/api/client", json=payload)

    @mcp.tool
    async def update_client(
        client_id: int,
        first_name: str = "",
        last_name: str = "",
        phone: str = "",
        email: str = "",
    ) -> dict:
        """Update an existing client's information.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            client_id: ID of the client to update.
            first_name: New first name (leave empty to keep current).
            last_name: New last name (leave empty to keep current).
            phone: New phone number.
            email: New email address.
        """
        client = VetmanagerClient()
        payload: dict = {}
        if first_name:
            payload["firstName"] = first_name
        if last_name:
            payload["lastName"] = last_name
        if phone:
            payload["phone"] = phone
        if email:
            payload["email"] = email
        return await client.put(f"/rest/api/client/{client_id}", json=payload)

    @mcp.tool
    async def get_client_profile(
        client_id: int,
    ) -> dict:
        """Get a comprehensive profile for a client in one call.

        Aggregates:
        - Full client record
        - Last 5 invoices with line items (invoiceDocuments) and payment status
        - Last 5 admissions (visits)
        - Next scheduled admission (status=active, earliest date)

        Args:
            client_id: Unique numeric ID of the client.
        """
        import json as _json

        vc = VetmanagerClient()

        client_data_resp = await vc.get(f"/rest/api/client/{client_id}")
        client_data = client_data_resp.get("data", {}).get("client", {})

        invoice_filter = _json.dumps(
            [{"property": "client_id", "value": str(client_id)}],
            separators=(",", ":"),
        )
        invoice_sort = _json.dumps(
            [{"property": "id", "direction": "DESC"}],
            separators=(",", ":"),
        )
        invoices_resp = await vc.get(
            "/rest/api/invoice",
            params={"filter": invoice_filter, "sort": invoice_sort, "limit": 5},
        )
        invoices = invoices_resp.get("data", {}).get("invoice", [])

        admission_filter = _json.dumps(
            [{"property": "client_id", "value": str(client_id)}],
            separators=(",", ":"),
        )
        admission_sort = _json.dumps(
            [{"property": "admission_date", "direction": "DESC"}],
            separators=(",", ":"),
        )
        admissions_resp = await vc.get(
            "/rest/api/admission",
            params={"filter": admission_filter, "sort": admission_sort, "limit": 5},
        )
        admissions = admissions_resp.get("data", {}).get("admission", [])

        next_admission_filter = _json.dumps(
            [
                {"property": "client_id", "value": str(client_id)},
                {"property": "status", "value": "active"},
            ],
            separators=(",", ":"),
        )
        next_admission_sort = _json.dumps(
            [{"property": "admission_date", "direction": "ASC"}],
            separators=(",", ":"),
        )
        next_admission_resp = await vc.get(
            "/rest/api/admission",
            params={
                "filter": next_admission_filter,
                "sort": next_admission_sort,
                "limit": 1,
            },
        )
        next_admissions = next_admission_resp.get("data", {}).get("admission", [])
        next_admission = next_admissions[0] if next_admissions else None

        return {
            "client": client_data,
            "last_invoices": invoices,
            "last_admissions": admissions,
            "next_admission": next_admission,
        }

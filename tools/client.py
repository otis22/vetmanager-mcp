import json
from fastmcp import FastMCP

from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clients(
        limit: LimitParam = 20,
        offset: int = 0,
        name: str = "",
        status: str = "ACTIVE",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List clients of the clinic.

        By default only ACTIVE clients are returned.  Pass status="" to include
        all statuses (ACTIVE, DELETED, INACTIVE).

        Args:
            limit: Max number of records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            name: Filter by client name (partial match).
            status: Filter by client status: 'ACTIVE' (default), 'DELETED',
                    'INACTIVE', or '' for all.
        """
        client = VetmanagerClient()

        combined_filters: list[dict] = list(filter or [])
        if status:
            combined_filters.append(
                {"property": "status", "value": status, "operator": "="}
            )

        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
            extra={"name": name},
        )
        return await client.get("/rest/api/client", params=params)

    @mcp.tool
    async def get_debtors(
        limit: LimitParam = 100,
        offset: int = 0,
    ) -> dict:
        """List all ACTIVE clients who have a negative balance (debtors).

        Iterates through all active clients using pagination and returns only
        those whose balance field is negative.  The result includes client name,
        phone, and balance amount.

        Args:
            limit: Max clients to fetch per page (1–100, default 100).
            offset: Pagination offset (0–10000).
        """
        vc = VetmanagerClient()
        active_filter = json.dumps(
            [{"property": "status", "value": "ACTIVE", "operator": "="}],
            separators=(",", ":"),
        )
        debtors: list[dict] = []
        current_offset = offset
        total_fetched = 0

        while True:
            params: dict = {
                "filter": active_filter,
                "limit": limit,
                "offset": current_offset,
            }
            resp = await vc.get("/rest/api/client", params=params)
            data = resp.get("data", {})
            total_count = int(data.get("totalCount", 0)) if isinstance(data, dict) else 0
            clients = data.get("client", []) if isinstance(data, dict) else []

            if not clients:
                break

            for c in clients:
                balance_raw = c.get("balance")
                try:
                    balance = float(balance_raw) if balance_raw is not None else None
                except (TypeError, ValueError):
                    balance = None
                if balance is not None and balance < 0:
                    debtors.append(
                        {
                            "id": c.get("id"),
                            "last_name": c.get("last_name", ""),
                            "first_name": c.get("first_name", ""),
                            "middle_name": c.get("middle_name", ""),
                            "cell_phone": c.get("cell_phone", ""),
                            "home_phone": c.get("home_phone", ""),
                            "balance": balance,
                            "status": c.get("status", ""),
                        }
                    )

            total_fetched += len(clients)
            current_offset += len(clients)

            # Stop when we've fetched all records.
            if total_fetched >= total_count or len(clients) < limit:
                break

        return {
            "success": True,
            "debtors_count": len(debtors),
            "total_active_clients_checked": total_fetched,
            "debtors": debtors,
        }

    @mcp.tool
    async def get_client_by_id(
        client_id: int,
    ) -> dict:
        """Get a clinic client by their unique ID.

        Args:
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
        middle_name: str = "",
        phone: str = "",
        cell_phone: str = "",
        email: str = "",
        address: str = "",
        city_id: int = 0,
        street_id: int = 0,
        note: str = "",
        status: str = "",
    ) -> dict:
        """Update an existing client's information.

        Args:
            client_id: ID of the client to update.
            first_name: New first name (leave empty to keep current).
            last_name: New last name (leave empty to keep current).
            middle_name: New middle name (leave empty to keep current).
            phone: New home phone number.
            cell_phone: New cell phone number.
            email: New email address.
            address: New postal address.
            city_id: New city ID (0 = no change).
            street_id: New street ID (0 = no change).
            note: Updated notes.
            status: New status: 'ACTIVE', 'DELETED', 'INACTIVE' (leave empty to keep current).
        """
        client = VetmanagerClient()
        payload: dict = {}
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        if middle_name:
            payload["middle_name"] = middle_name
        if phone:
            payload["home_phone"] = phone
        if cell_phone:
            payload["cell_phone"] = cell_phone
        if email:
            payload["email"] = email
        if address:
            payload["address"] = address
        if city_id:
            payload["city_id"] = city_id
        if street_id:
            payload["street_id"] = street_id
        if note:
            payload["note"] = note
        if status:
            payload["status"] = status
        return await client.put(f"/rest/api/client/{client_id}", json=payload)

    @mcp.tool
    async def delete_client(
        client_id: int,
    ) -> dict:
        """Delete a client by their ID.

        WARNING: This permanently removes the client record. Use with caution.

        Args:
            client_id: ID of the client to delete.
        """
        vc = VetmanagerClient()
        return await vc.delete(f"/rest/api/client/{client_id}")

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

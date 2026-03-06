import json
from fastmcp import FastMCP

from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_invoices(
        limit: LimitParam = 20,
        offset: int = 0,
        client_id: int = 0,
        date_from: str = "",
        date_to: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List invoices in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            client_id: Filter by client ID (0 = no filter).
            date_from: Filter invoices created on or after this date (YYYY-MM-DD, optional).
            date_to: Filter invoices created on or before this date (YYYY-MM-DD, optional).
        """
        vc = VetmanagerClient()

        combined_filters: list[dict] = list(filter or [])
        if date_from:
            combined_filters.append(
                {"property": "create_date", "value": date_from, "operator": ">="}
            )
        if date_to:
            combined_filters.append(
                {"property": "create_date", "value": date_to, "operator": "<="}
            )

        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
            extra={"client_id": client_id},
        )
        return await vc.get("/rest/api/invoice", params=params)

    @mcp.tool
    async def get_average_invoice(
        date_from: str = "",
        date_to: str = "",
    ) -> dict:
        """Calculate the average invoice (average check) for a given period.

        Fetches all invoices in the specified date range using pagination and
        computes the average, total, and count.  If no dates are provided the
        last 365 days are used.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            date_from: Start date in YYYY-MM-DD format (optional, default: 1 year ago).
            date_to: End date in YYYY-MM-DD format (optional, default: today).
        """
        from datetime import date, timedelta

        vc = VetmanagerClient()

        today = date.today()
        if not date_to:
            date_to = today.isoformat()
        if not date_from:
            date_from = (today - timedelta(days=365)).isoformat()

        combined_filters = [
            {"property": "create_date", "value": date_from, "operator": ">="},
            {"property": "create_date", "value": date_to, "operator": "<="},
        ]
        filter_str = json.dumps(combined_filters, separators=(",", ":"))

        total_sum = 0.0
        total_count = 0
        offset = 0
        page_size = 100

        while True:
            params = {
                "filter": filter_str,
                "limit": page_size,
                "offset": offset,
            }
            resp = await vc.get("/rest/api/invoice", params=params)
            data = resp.get("data", {})
            total_records = int(data.get("totalCount", 0)) if isinstance(data, dict) else 0
            invoices = data.get("invoice", []) if isinstance(data, dict) else []

            if not invoices:
                break

            for inv in invoices:
                amount_raw = inv.get("amount") or inv.get("total") or inv.get("sum") or 0
                try:
                    amount = float(amount_raw)
                except (TypeError, ValueError):
                    amount = 0.0
                if amount > 0:
                    total_sum += amount
                    total_count += 1

            offset += len(invoices)
            if offset >= total_records or len(invoices) < page_size:
                break

        average = round(total_sum / total_count, 2) if total_count > 0 else 0.0

        return {
            "success": True,
            "date_from": date_from,
            "date_to": date_to,
            "invoices_with_amount": total_count,
            "total_revenue": round(total_sum, 2),
            "average_invoice": average,
        }

    @mcp.tool
    async def get_invoice_by_id(
        invoice_id: int,
    ) -> dict:
        """Get a specific invoice by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            invoice_id: Unique numeric ID of the invoice.
        """
        vc = VetmanagerClient()
        return await vc.get(f"/rest/api/invoice/{invoice_id}")

    @mcp.tool
    async def create_invoice(
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
        vc = VetmanagerClient()
        payload: dict = {"client_id": client_id, "pet_id": pet_id}
        if description:
            payload["description"] = description
        return await vc.post("/rest/api/invoice", json=payload)

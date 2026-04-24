from datetime import date, timedelta

from fastmcp import FastMCP

from filters import eq as _filter_eq, gte as _filter_gte, lte as _filter_lte
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete, paginate_all
from validators import LimitParam, parse_date_param


def register(mcp: FastMCP) -> None:

    _INVOICE_PAYMENT_STATUSES = {"none", "partial", "full"}

    @mcp.tool
    async def get_invoices(
        limit: LimitParam = 20,
        offset: int = 0,
        client_id: int = 0,
        pet_id: int = 0,
        payment_status: str = "",
        date_from: str = "",
        date_to: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List invoices in the clinic.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            client_id: Filter by client ID (0 = no filter).
            pet_id: Filter by pet ID (0 = no filter).
            payment_status: Filter by payment status. Valid values: 'none'
                (unpaid), 'partial' (partially paid), 'full' (fully paid).
                This is the payment state of the invoice, distinct from the
                workflow `status` field (exec/save/deleted).
            date_from: Filter invoices created on or after this date.
                Accepts YYYY-MM-DD or relative: today, yesterday, tomorrow,
                +Nd/-Nd, +Nw/-Nw, +Nm/-Nm.
            date_to: Filter invoices created on or before this date.
                Same accepted formats as `date_from`.
        """
        if payment_status and payment_status not in _INVOICE_PAYMENT_STATUSES:
            raise ValueError(
                f"payment_status must be one of {sorted(_INVOICE_PAYMENT_STATUSES)}, "
                f"got '{payment_status}'"
            )

        resolved_date_from = parse_date_param(date_from)
        resolved_date_to = parse_date_param(date_to)

        combined_filters: list = list(filter or [])
        if resolved_date_from:
            combined_filters.append(_filter_gte("create_date", resolved_date_from))
        if resolved_date_to:
            combined_filters.append(_filter_lte("create_date", resolved_date_to))
        if client_id:
            combined_filters.append(_filter_eq("client_id", client_id))
        if pet_id:
            combined_filters.append(_filter_eq("pet_id", pet_id))
        if payment_status:
            combined_filters.append(_filter_eq("payment_status", payment_status))

        return await crud_list(
            "/rest/api/invoice", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

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
            date_from: Start date. Accepts YYYY-MM-DD or relative forms
                (today, -30d, -1m, ...). Default: 1 year ago.
            date_to: End date. Same accepted formats. Default: today.
        """
        today = date.today()
        if not date_to:
            date_to = today.isoformat()
        else:
            date_to = parse_date_param(date_to)
        if not date_from:
            date_from = (today - timedelta(days=365)).isoformat()
        else:
            date_from = parse_date_param(date_from)

        combined_filters = [
            _filter_gte("create_date", date_from),
            _filter_lte("create_date", date_to),
        ]

        invoices, _ = await paginate_all(
            "/rest/api/invoice",
            filters=combined_filters,
            page_size=100,
            entity_key="invoice",
        )

        total_sum = 0.0
        total_count = 0
        for inv in invoices:
            amount_raw = inv.get("amount") or inv.get("total") or inv.get("sum") or 0
            try:
                amount = float(amount_raw)
            except (TypeError, ValueError):
                amount = 0.0
            if amount > 0:
                total_sum += amount
                total_count += 1

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
            invoice_id: Unique numeric ID of the invoice.
        """
        return await crud_get_by_id("/rest/api/invoice", invoice_id)

    @mcp.tool
    async def create_invoice(
        client_id: int,
        pet_id: int,
        description: str = "",
    ) -> dict:
        """Create a new invoice for a client/pet.

        Args:
            client_id: ID of the client being invoiced.
            pet_id: ID of the pet the invoice is for.
            description: Optional description for the invoice.
        """
        payload: dict = {"client_id": client_id, "pet_id": pet_id}
        if description:
            payload["description"] = description
        return await crud_create("/rest/api/invoice", payload)

    @mcp.tool
    async def update_invoice(
        invoice_id: int,
        client_id: int = 0,
        pet_id: int = 0,
        description: str = "",
        status: str = "",
        percent: float = 0.0,
        discount: float = 0.0,
    ) -> dict:
        """Update an existing invoice.

        Args:
            invoice_id: ID of the invoice to update.
            client_id: New client ID (0 = no change).
            pet_id: New pet ID (0 = no change).
            description: Updated description (leave empty to keep current).
            status: Updated invoice status (leave empty to keep current).
            percent: Updated percent value (0 = no change).
            discount: Updated discount value (0 = no change).
        """
        payload: dict = {}
        if client_id:
            payload["client_id"] = client_id
        if pet_id:
            payload["pet_id"] = pet_id
        if description:
            payload["description"] = description
        if status:
            payload["status"] = status
        if percent:
            payload["percent"] = percent
        if discount:
            payload["discount"] = discount
        return await crud_update("/rest/api/invoice", invoice_id, payload)

    @mcp.tool
    async def delete_invoice(
        invoice_id: int,
    ) -> dict:
        """Delete an invoice by its ID.

        WARNING: This permanently removes the invoice. Use with caution.

        Args:
            invoice_id: ID of the invoice to delete.
        """
        return await crud_delete("/rest/api/invoice", invoice_id)

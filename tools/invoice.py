from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from fastmcp import FastMCP

from filters import build_list_query_params, eq as _filter_eq, gte as _filter_gte, lt as _filter_lt, lte as _filter_lte
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete, paginate_all
from validators import LimitParam, parse_date_param
from vetmanager_client import VetmanagerClient

_MONEY_QUANT = Decimal("0.01")
_SUMMARY_PAGE_SIZE = 100
_SUMMARY_PAGE_CAP = 20


def register(mcp: FastMCP) -> None:

    _INVOICE_PAYMENT_STATUSES = {"none", "partial", "full"}
    _INVOICE_STATUSES = {"exec", "save", "deleted", "closed", "archived"}
    _REVENUE_SUMMARY_MODES = {
        "received",
        "invoiced",
        "paid_by_executed_invoices",
    }

    def _parse_money_filter(value: str, *, field_name: str) -> str:
        if value == "":
            return ""
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"{field_name} must be a decimal value, got '{value}'") from exc
        if not parsed.is_finite():
            raise ValueError(f"{field_name} must be a finite decimal value, got '{value}'")
        return str(value)

    def _parse_date_range(date_from: str, date_to: str, *, label: str) -> tuple[str, str]:
        resolved_from = parse_date_param(date_from)
        resolved_to = parse_date_param(date_to)
        if resolved_from and resolved_to and resolved_from > resolved_to:
            raise ValueError(f"{label}_from must be on or before {label}_to")
        return resolved_from, resolved_to

    def _next_day_start(date_value: str) -> str:
        return (date.fromisoformat(date_value) + timedelta(days=1)).isoformat() + " 00:00:00"

    def _day_start(date_value: str) -> str:
        return f"{date_value} 00:00:00"

    def _money(value: Any, *, field_name: str, row_id: Any) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(
                f"Invalid {field_name} value in {row_id=}: '{value}'"
            ) from exc
        if not parsed.is_finite():
            raise ValueError(
                f"Invalid non-finite {field_name} value in {row_id=}: '{value}'"
            )
        return parsed

    def _money_str(value: Decimal) -> str:
        return str(value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_UP))

    @mcp.tool
    async def get_invoices(
        limit: LimitParam = 20,
        offset: int = 0,
        client_id: int = 0,
        pet_id: int = 0,
        payment_status: str = "",
        status: str = "",
        date_from: str = "",
        date_to: str = "",
        invoice_date_from: str = "",
        invoice_date_to: str = "",
        paid_amount_min: str = "",
        paid_amount_max: str = "",
        amount_min: str = "",
        amount_max: str = "",
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
            status: Filter by invoice workflow status. Valid values: 'exec',
                'save', 'deleted', 'closed', 'archived'.
            date_from: Filter invoices created on or after this date.
                Accepts YYYY-MM-DD or relative: today, yesterday, tomorrow,
                +Nd/-Nd, +Nw/-Nw, +Nm/-Nm.
            date_to: Filter invoices created on or before this date.
                Same accepted formats as `date_from`.
            invoice_date_from: Filter executed invoices on or after the start
                of this local clinic date.
            invoice_date_to: Filter executed invoices before the next local
                clinic day after this date.
            paid_amount_min: Minimum paid amount filter.
            paid_amount_max: Maximum paid amount filter.
            amount_min: Minimum invoice amount filter.
            amount_max: Maximum invoice amount filter.
        """
        if payment_status and payment_status not in _INVOICE_PAYMENT_STATUSES:
            raise ValueError(
                f"payment_status must be one of {sorted(_INVOICE_PAYMENT_STATUSES)}, "
                f"got '{payment_status}'"
            )
        if status and status not in _INVOICE_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_INVOICE_STATUSES)}, got '{status}'"
            )
        if (date_from or date_to) and (invoice_date_from or invoice_date_to):
            raise ValueError(
                "date_from/date_to filter create_date; invoice_date_from/"
                "invoice_date_to filter financial invoice_date. Do not mix them."
            )

        resolved_date_from, resolved_date_to = _parse_date_range(
            date_from, date_to, label="date"
        )
        resolved_invoice_date_from, resolved_invoice_date_to = _parse_date_range(
            invoice_date_from, invoice_date_to, label="invoice_date"
        )
        resolved_paid_amount_min = _parse_money_filter(
            paid_amount_min, field_name="paid_amount_min"
        )
        resolved_paid_amount_max = _parse_money_filter(
            paid_amount_max, field_name="paid_amount_max"
        )
        resolved_amount_min = _parse_money_filter(amount_min, field_name="amount_min")
        resolved_amount_max = _parse_money_filter(amount_max, field_name="amount_max")

        combined_filters: list = list(filter or [])
        if resolved_date_from:
            combined_filters.append(_filter_gte("create_date", resolved_date_from))
        if resolved_date_to:
            combined_filters.append(_filter_lte("create_date", resolved_date_to))
        if resolved_invoice_date_from:
            combined_filters.append(
                _filter_gte("invoice_date", _day_start(resolved_invoice_date_from))
            )
        if resolved_invoice_date_to:
            combined_filters.append(
                _filter_lt("invoice_date", _next_day_start(resolved_invoice_date_to))
            )
        if client_id:
            combined_filters.append(_filter_eq("client_id", client_id))
        if pet_id:
            combined_filters.append(_filter_eq("pet_id", pet_id))
        if payment_status:
            combined_filters.append(_filter_eq("payment_status", payment_status))
        if status:
            combined_filters.append(_filter_eq("status", status))
        elif resolved_invoice_date_from or resolved_invoice_date_to:
            combined_filters.append(_filter_eq("status", "exec"))
        if resolved_paid_amount_min:
            combined_filters.append(_filter_gte("paid_amount", resolved_paid_amount_min))
        if resolved_paid_amount_max:
            combined_filters.append(_filter_lte("paid_amount", resolved_paid_amount_max))
        if resolved_amount_min:
            combined_filters.append(_filter_gte("amount", resolved_amount_min))
        if resolved_amount_max:
            combined_filters.append(_filter_lte("amount", resolved_amount_max))

        return await crud_list(
            "/rest/api/invoice", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_revenue_summary(
        date_from: str,
        date_to: str,
        mode: str = "received",
        include_breakdown: bool = True,
        client_id: int = 0,
    ) -> dict:
        """Summarize revenue for a date range with safe financial defaults.

        Args:
            date_from: Start date. Accepts YYYY-MM-DD or relative forms.
            date_to: End date. Same accepted formats.
            mode: 'received' for cash revenue from exec payments, 'invoiced'
                for executed invoice amount, or 'paid_by_executed_invoices'
                for current paid_amount on invoices executed in the period.
            include_breakdown: Include day-level totals.
            client_id: Optional client filter (0 = no filter).
        """
        if mode not in _REVENUE_SUMMARY_MODES:
            raise ValueError(
                f"mode must be one of {sorted(_REVENUE_SUMMARY_MODES)}, got '{mode}'"
            )

        resolved_from, resolved_to = _parse_date_range(
            date_from, date_to, label="date"
        )
        if not resolved_from or not resolved_to:
            raise ValueError("date_from and date_to are required")

        if mode == "received":
            endpoint = "/rest/api/payment"
            entity_key = "payment"
            source = "payment"
            date_field = "create_date"
            amount_field = "amount"
            cashflow = True
        else:
            endpoint = "/rest/api/invoice"
            entity_key = "invoice"
            source = "invoice"
            date_field = "invoice_date"
            amount_field = "amount" if mode == "invoiced" else "paid_amount"
            cashflow = False

        filters = [
            _filter_eq("status", "exec"),
            _filter_gte(date_field, _day_start(resolved_from)),
            _filter_lt(date_field, _next_day_start(resolved_to)),
        ]
        if client_id:
            filters.append(_filter_eq("client_id", client_id))

        sort = [{"property": "id", "direction": "ASC"}]
        vc = VetmanagerClient()
        total = Decimal("0")
        by_day: dict[str, dict[str, Any]] = {}
        scanned_count = 0
        returned_count = 0
        total_count: int | None = None
        warnings: list[str] = []
        offset = 0

        for _page in range(_SUMMARY_PAGE_CAP):
            params = build_list_query_params(
                limit=_SUMMARY_PAGE_SIZE,
                offset=offset,
                sort=sort,
                filters=filters,
            )
            response = await vc.get(endpoint, params=params)
            data = response.get("data", {})
            records = data.get(entity_key, []) if isinstance(data, dict) else []
            if total_count is None and isinstance(data, dict) and "totalCount" in data:
                try:
                    total_count = int(data["totalCount"])
                except (TypeError, ValueError):
                    total_count = None

            if not records:
                break

            for row in records:
                amount = _money(
                    row.get(amount_field),
                    field_name=amount_field,
                    row_id=row.get("id", "unknown"),
                )
                total += amount
                scanned_count += 1
                returned_count += 1
                if include_breakdown:
                    day = str(row.get(date_field, ""))[:10] or "unknown"
                    bucket = by_day.setdefault(
                        day, {"date": day, "total": Decimal("0"), "count": 0}
                    )
                    bucket["total"] += amount
                    bucket["count"] += 1

            offset += len(records)
            if len(records) < _SUMMARY_PAGE_SIZE:
                break
            if total_count is not None and offset >= total_count:
                break

        truncated = False
        if total_count is not None and scanned_count < total_count:
            truncated = True
        elif total_count is None and scanned_count >= _SUMMARY_PAGE_SIZE * _SUMMARY_PAGE_CAP:
            truncated = True

        if truncated:
            warnings.append(
                "Partial result: totals are incomplete and must not be presented "
                "as final revenue. Narrow the date range or filters."
            )

        by_day_list = []
        if include_breakdown:
            for day in sorted(by_day):
                bucket = by_day[day]
                by_day_list.append(
                    {
                        "date": day,
                        "total_amount": _money_str(bucket["total"]),
                        "count": bucket["count"],
                    }
                )

        return {
            "success": True,
            "mode": mode,
            "source": source,
            "cashflow": cashflow,
            "date_from": resolved_from,
            "date_to": resolved_to,
            "date_field": date_field,
            "amount_field": amount_field,
            "total_amount": _money_str(total),
            "returned_count": returned_count,
            "scanned_count": scanned_count,
            "total_count": total_count,
            "page_cap": _SUMMARY_PAGE_CAP,
            "page_size": _SUMMARY_PAGE_SIZE,
            "truncated": truncated,
            "warnings": warnings,
            "applied_filters": [f.to_dict() for f in filters],
            "sort": sort,
            "by_day": by_day_list,
        }

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

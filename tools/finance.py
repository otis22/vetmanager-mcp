"""Financial entity tools: Payment, ClosingOfInvoices, InvoiceDocument, Cassa, CassaClose."""

from datetime import date, timedelta

from fastmcp import FastMCP
from filters import (
    eq as _filter_eq,
    gte as _filter_gte,
    in_ as _filter_in,
    lt as _filter_lt,
)
from tools.crud_helpers import crud_list, crud_get_by_id, crud_delete
from validators import LimitParam, parse_date_param


def register(mcp: FastMCP) -> None:

    _PAYMENT_STATUSES = {"exec", "save", "deleted"}
    _INVOICE_DOCUMENT_FILTER_FIELDS = {"invoice_id", "invoiceId", "documentId", "document_id"}
    _CLIENT_PAYMENT_INVOICE_ID_CAP = 100

    def _parse_date_range(date_from: str, date_to: str, *, label: str) -> tuple[str, str]:
        resolved_from = parse_date_param(date_from)
        resolved_to = parse_date_param(date_to)
        if resolved_from and resolved_to and resolved_from > resolved_to:
            raise ValueError(f"{label}_from must be on or before {label}_to")
        return resolved_from, resolved_to

    def _day_start(date_value: str) -> str:
        return f"{date_value} 00:00:00"

    def _next_day_start(date_value: str) -> str:
        next_day = date.fromisoformat(date_value) + timedelta(days=1)
        return f"{next_day.isoformat()} 00:00:00"

    def _reject_payment_create_date_filter_conflict(filters: list[dict] | None) -> None:
        for item in filters or []:
            if not isinstance(item, dict):
                continue
            if item.get("property") == "create_date":
                raise ValueError(
                    "Do not pass create_date in filter together with date_from/date_to. "
                    "Use date_from/date_to for payment date range, or omit them and pass "
                    "a raw create_date filter explicitly."
                )

    def _reject_payment_client_filter(filters: list[dict] | None) -> None:
        for item in filters or []:
            if not isinstance(item, dict):
                continue
            if item.get("property") in {"client_id", "clientId"}:
                raise ValueError(
                    "Vetmanager Payment REST does not support client_id filter. "
                    "Use get_client_payment_applications(client_id=...) for "
                    "client-scoped payment applications."
                )

    def _reject_invoice_document_parent_filters(filters: list[dict] | None) -> None:
        for item in filters or []:
            if not isinstance(item, dict):
                continue
            if item.get("property") in _INVOICE_DOCUMENT_FILTER_FIELDS:
                raise ValueError(
                    "Use the invoice_id argument for get_invoice_documents; "
                    "it is converted to document_id internally. Do not also pass "
                    "invoice_id/invoiceId/documentId/document_id in filter."
                )

    def _extract_entity_rows(resp: dict, entity_key: str) -> tuple[list[dict], int | None]:
        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)], None
        if not isinstance(data, dict):
            return [], None
        rows = data.get(entity_key) or []
        total = data.get("totalCount")
        try:
            parsed_total = int(total) if total is not None else None
        except (TypeError, ValueError):
            parsed_total = None
        return [row for row in rows if isinstance(row, dict)], parsed_total

    def _result_metadata(
        *,
        rows: list[dict],
        total: int | None,
        limit: int,
        offset: int,
        client_id: int,
        pet_id: int,
        date_from: str,
        date_to: str,
    ) -> dict:
        truncated = None if total is None else offset + len(rows) < total
        return {
            "client_id": client_id,
            "pet_id": pet_id or None,
            "date_from": date_from or None,
            "date_to": date_to or None,
            "limit": limit,
            "offset": offset,
            "count": len(rows),
            "total": total,
            "truncated": truncated,
            "closingOfInvoices": rows,
        }

    def _coerce_invoice_id(value) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    async def _invoice_ids_for_client_pet(client_id: int, pet_id: int) -> list[int]:
        invoice_resp = await crud_list(
            "/rest/api/invoice",
            limit=_CLIENT_PAYMENT_INVOICE_ID_CAP,
            offset=0,
            filters=[_filter_eq("client_id", client_id), _filter_eq("pet_id", pet_id)],
        )
        if isinstance(invoice_resp, dict) and invoice_resp.get("success") is False:
            message = invoice_resp.get("message") or "Invoice lookup failed"
            raise ValueError(
                "Invoice lookup failed for get_client_payment_applications "
                f"pet filter: {message}"
            )
        rows, total = _extract_entity_rows(invoice_resp, "invoice")
        if total is not None and total > _CLIENT_PAYMENT_INVOICE_ID_CAP:
            raise ValueError(
                "pet filter matched too many invoices for get_client_payment_applications "
                f"({total} > {_CLIENT_PAYMENT_INVOICE_ID_CAP}). Use the client-level "
                "call without pet_id and filter returned invoice.pet_id, or query a "
                "narrower pet context separately."
            )
        if total is None and len(rows) >= _CLIENT_PAYMENT_INVOICE_ID_CAP:
            raise ValueError(
                "pet filter may have more invoices than get_client_payment_applications "
                f"can safely query ({_CLIENT_PAYMENT_INVOICE_ID_CAP} rows with unknown total). "
                "Use the client-level call without pet_id and filter returned invoice.pet_id, "
                "or query a narrower pet context separately."
            )
        invoice_ids: list[int] = []
        for row in rows:
            invoice_id = _coerce_invoice_id(row.get("id"))
            if invoice_id is not None:
                invoice_ids.append(invoice_id)
        return invoice_ids

    @mcp.tool
    async def get_payments(
        limit: LimitParam = 20,
        offset: int = 0,
        client_id: int = 0,
        status: str = "",
        date_from: str = "",
        date_to: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List client payments in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            client_id: Deprecated unsupported filter. Vetmanager Payment REST
                has no client_id field; use get_client_payment_applications
                for client-scoped payment applications.
            status: Filter by payment workflow status. Valid values:
                'exec' (posted), 'save' (draft), 'deleted'.
            date_from: Filter payments created on or after this date.
                Accepts YYYY-MM-DD or relative: today, yesterday, tomorrow,
                +Nd/-Nd, +Nw/-Nw, +Nm/-Nm.
            date_to: Filter payments through this local clinic date (inclusive);
                implemented as create_date < next day's 00:00:00. Same accepted
                formats as `date_from`.
        """
        if status and status not in _PAYMENT_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_PAYMENT_STATUSES)}, got '{status}'"
            )
        if client_id:
            raise ValueError(
                "Vetmanager Payment REST does not support client_id filter. "
                "Use get_client_payment_applications(client_id=...) for "
                "client-scoped payment applications."
            )
        _reject_payment_client_filter(filter)

        resolved_date_from, resolved_date_to = _parse_date_range(
            date_from, date_to, label="date"
        )
        if resolved_date_from or resolved_date_to:
            _reject_payment_create_date_filter_conflict(filter)

        combined_filters: list = list(filter or [])
        if resolved_date_from:
            combined_filters.append(
                _filter_gte("create_date", _day_start(resolved_date_from))
            )
        if resolved_date_to:
            combined_filters.append(_filter_lt("create_date", _next_day_start(resolved_date_to)))
        if status:
            combined_filters.append(_filter_eq("status", status))
        return await crud_list(
            "/rest/api/payment", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_client_payment_applications(
        client_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        pet_id: int = 0,
        date_from: str = "",
        date_to: str = "",
        sort: list[dict] | None = None,
    ) -> dict:
        """List payment applications for a client via closingOfInvoices.

        This is the correct client-scoped finance path: Payment rows do not
        have client_id or pet_id directly. Vetmanager links client/invoice and
        payment through closingOfInvoices rows. The result is not a complete
        list of unapplied/advance payments; it returns payment applications
        represented by closingOfInvoices with plus_type_document='payment'.

        Args:
            client_id: Required client ID.
            limit: Max records to return.
            offset: Pagination offset.
            pet_id: Optional pet/patient filter via client invoices.
            date_from: Filter application create_date on or after this date.
            date_to: Filter application create_date through this local clinic
                date (inclusive), implemented as < next day 00:00:00.
        """
        if client_id <= 0:
            raise ValueError("client_id is required")
        if pet_id < 0:
            raise ValueError("pet_id must be positive or 0")
        resolved_date_from, resolved_date_to = _parse_date_range(
            date_from, date_to, label="date"
        )

        filters: list = [
            _filter_eq("client_id", client_id),
            _filter_eq("plus_type_document", "payment"),
        ]
        if resolved_date_from:
            filters.append(_filter_gte("create_date", _day_start(resolved_date_from)))
        if resolved_date_to:
            filters.append(_filter_lt("create_date", _next_day_start(resolved_date_to)))
        if pet_id:
            invoice_ids = await _invoice_ids_for_client_pet(client_id, pet_id)
            if not invoice_ids:
                return {
                    "success": True,
                    "data": _result_metadata(
                        rows=[],
                        total=0,
                        limit=limit,
                        offset=offset,
                        client_id=client_id,
                        pet_id=pet_id,
                        date_from=resolved_date_from,
                        date_to=resolved_date_to,
                    ),
                }
            filters.extend([
                _filter_eq("minus_type_document", "invoice"),
                _filter_in("minus_document_id", invoice_ids),
            ])

        response = await crud_list(
            "/rest/api/closingOfInvoices",
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filters,
        )
        rows, total = _extract_entity_rows(response, "closingOfInvoices")
        success = response.get("success", True) if isinstance(response, dict) else True
        if success is False:
            return {
                "success": False,
                "message": response.get("message") or "closingOfInvoices lookup failed",
                "data": _result_metadata(
                    rows=rows,
                    total=total,
                    limit=limit,
                    offset=offset,
                    client_id=client_id,
                    pet_id=pet_id,
                    date_from=resolved_date_from,
                    date_to=resolved_date_to,
                ),
            }
        return {
            "success": success,
            "data": _result_metadata(
                rows=rows,
                total=total,
                limit=limit,
                offset=offset,
                client_id=client_id,
                pet_id=pet_id,
                date_from=resolved_date_from,
                date_to=resolved_date_to,
            ),
        }

    @mcp.tool
    async def get_payment_by_id(payment_id: int) -> dict:
        """Get a payment record by its unique ID.

        Args:
            payment_id: Unique numeric ID of the payment.
        """
        return await crud_get_by_id("/rest/api/payment", payment_id)

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
            filter: Extra filters; do not pass invoice_id/invoiceId/documentId/document_id.
                Use the invoice_id argument for parent invoice filtering.
        """
        _reject_invoice_document_parent_filters(filter)
        combined_filters: list = list(filter or [])
        combined_filters.append(_filter_eq("document_id", invoice_id))
        return await crud_list(
            "/rest/api/invoiceDocument", limit=limit, offset=offset,
            sort=sort, filters=combined_filters,
        )

    @mcp.tool
    async def get_invoice_document_by_id(doc_id: int) -> dict:
        """Get a single invoice line item by its unique ID.

        Args:
            doc_id: Unique numeric ID of the invoice document.
        """
        return await crud_get_by_id("/rest/api/invoiceDocument", doc_id)

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

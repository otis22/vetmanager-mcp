from fastmcp import FastMCP

from filters import eq as _filter_eq, in_ as _filter_in, like as _filter_like
from tools._inactive_helpers import fetch_inactive_clients_page
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete, paginate_all
from validators import LimitParam, normalize_phone_digits


# Hard cap on phase-1 ClientPhone fetch. If more rows exist we refuse the
# search rather than silently return a truncated set of clients.
_PHONE_SEARCH_MAX_ROWS = 100


async def _search_client_phones(search_digits: str) -> list[int]:
    """Phase-1 helper: return client_ids whose clean_phone LIKE search_digits.

    Raises ValueError if the result set is too broad to be useful.
    """
    resp = await crud_list(
        "/rest/api/ClientPhone",
        limit=_PHONE_SEARCH_MAX_ROWS,
        offset=0,
        filters=[_filter_like("clean_phone", search_digits)],
    )
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    if isinstance(data, dict):
        total = int(data.get("totalCount", 0) or 0)
        rows = data.get("clientPhone") or []
    else:
        total = 0
        rows = []
    if total > _PHONE_SEARCH_MAX_ROWS:
        raise ValueError(
            f"phone search too broad: matches {total} phone rows "
            f"(> {_PHONE_SEARCH_MAX_ROWS}). Provide more digits to narrow "
            "the search."
        )
    return sorted(
        {
            row.get("client_id")
            for row in rows
            if isinstance(row, dict) and row.get("client_id")
        }
    )


async def _resolve_client_ids_by_phone(phone_digits: str) -> list[int]:
    """Two-pass phone resolution: trailing 10 digits first, then full.

    The trailing-10 pass covers the common national 10-digit numbering
    plan (RU/US/CA/many others) regardless of country-code prefix in the
    user's input. If that yields nothing, we retry with the full
    normalized digits to handle non-10-digit plans (e.g. UK +44 XX).
    """
    if len(phone_digits) >= 11:
        primary = phone_digits[-10:]
        ids = await _search_client_phones(primary)
        if ids:
            return ids
        # Fallback: try the full normalized digits for non-10-digit plans.
        if phone_digits != primary:
            return await _search_client_phones(phone_digits)
        return ids
    return await _search_client_phones(phone_digits)


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clients(
        limit: LimitParam = 20,
        offset: int = 0,
        name: str = "",
        phone: str = "",
        email: str = "",
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
            phone: Filter by phone number (any of cell/home/work). The
                input is normalized to digits-only before matching against
                the `clients_phones.clean_phone` index, so formatted input
                like "+7 (918) 414-02-59" correctly finds the stored
                "(918)414-02-59". Must contain at least 4 digits.
            email: Filter by email address (LIKE match).
            status: Filter by client status: 'ACTIVE' (default), 'DELETED',
                    'INACTIVE', or '' for all.
        """
        combined_filters: list = list(filter or [])
        if status:
            combined_filters.append(_filter_eq("status", status))
        if phone:
            phone_digits = normalize_phone_digits(phone)
            if len(phone_digits) < 4:
                raise ValueError(
                    "phone filter requires at least 4 digits; shorter values "
                    "would match too many clients. Provide more of the number."
                )
            # Phase 1: search normalized phone index.
            #
            # Vetmanager stores phones with formatting in client.cell_phone/
            # home_phone/work_phone and maintains a parallel `clients_phones`
            # table with a digits-only `clean_phone` column, exposed via the
            # /rest/api/ClientPhone (case-sensitive) list endpoint.
            #
            # Country-code handling: `clean_phone` in the DB usually stores
            # local numbers without a country code (e.g. "9184140259"), but
            # LLMs often pass full international forms ("+7 918...", "8 918...").
            # We try the trailing 10 digits FIRST (covers the common 10-digit
            # national numbering plan used in RU/US/CA/etc), and if that
            # returns nothing, fall back to the full normalized digits. This
            # costs one extra round-trip only on genuinely unmatched inputs
            # and handles non-10-digit numbering plans (e.g. UK +44).
            client_ids = await _resolve_client_ids_by_phone(phone_digits)
            if not client_ids:
                return {
                    "success": True,
                    "data": {"client": [], "totalCount": 0},
                }
            # Phase 2: batch-fetch clients by id IN [...].
            combined_filters.append(_filter_in("id", client_ids))
        if email:
            combined_filters.append(_filter_like("email", email))

        return await crud_list(
            "/rest/api/client", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
            extra={"name": name},
        )

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
        clients, _ = await paginate_all(
            "/rest/api/client",
            filters=[_filter_eq("status", "ACTIVE")],
            page_size=limit,
            entity_key="client",
        )

        debtors: list[dict] = []
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

        return {
            "success": True,
            "debtors_count": len(debtors),
            "total_active_clients_checked": len(clients),
            "debtors": debtors,
        }

    @mcp.tool
    async def get_inactive_clients(
        months_min: int = 13,
        months_max: int = 24,
        limit: LimitParam = 50,
    ) -> dict:
        """Find lapsed clients who have not visited the clinic recently.

        Uses the server-side `client.last_visit_date` field to identify clients
        whose last visit falls within a window. Default window is 13–24 months
        ago — long enough to be lapsed but recent enough to reactivate.

        Returns the top N most recently lapsed clients (sorted by last_visit_date
        DESC). Default limit is 50 to prevent accidentally fetching the whole
        client base.

        Args:
            months_min: Minimum age of last visit in months (default 13).
            months_max: Maximum age of last visit in months (default 24).
            limit: Max clients to return (1–100, default 50).
        """
        clients, cutoff_oldest, cutoff_newest = await fetch_inactive_clients_page(
            months_min=months_min,
            months_max=months_max,
            limit=limit,
        )

        result_clients = [
            {
                "id": c.get("id"),
                "last_name": c.get("last_name", ""),
                "first_name": c.get("first_name", ""),
                "middle_name": c.get("middle_name", ""),
                "cell_phone": c.get("cell_phone", ""),
                "last_visit_date": c.get("last_visit_date", ""),
            }
            for c in clients[:limit]
        ]

        return {
            "inactive_clients": result_clients,
            "limit_applied": limit,
            "cutoff_window": {"from": cutoff_oldest, "to": cutoff_newest},
            "months_min": months_min,
            "months_max": months_max,
            "sort": "last_visit_date DESC",
            "note": (
                "Returned top N most recently lapsed clients. "
                "Pass higher limit (max 100) or different months_min/months_max to customize."
            ),
        }

    @mcp.tool
    async def get_client_by_id(
        client_id: int,
    ) -> dict:
        """Get a clinic client by their unique ID.

        Args:
            client_id: Unique numeric ID of the client.
        """
        return await crud_get_by_id("/rest/api/client", client_id)

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
        payload: dict = {"firstName": first_name, "lastName": last_name}
        if phone:
            payload["phone"] = phone
        if email:
            payload["email"] = email
        return await crud_create("/rest/api/client", payload)

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
        return await crud_update("/rest/api/client", client_id, payload)

    @mcp.tool
    async def delete_client(
        client_id: int,
    ) -> dict:
        """Delete a client by their ID.

        WARNING: This permanently removes the client record. Use with caution.

        Args:
            client_id: ID of the client to delete.
        """
        return await crud_delete("/rest/api/client", client_id)

    @mcp.tool
    async def get_client_profile(
        client_id: int,
    ) -> dict:
        """Get a comprehensive profile for a client in one call.

        Aggregates:
        - Full client record
        - Last 5 invoices with line items (invoiceDocuments) and payment status
        - Last 5 admissions (visits)
        - Next scheduled admission (earliest active-status date)

        Stage 102.2: tool-level latency + outcome metric via instrument_call
        wrapping the whole aggregator (sub-request latency is already covered
        by crud_helpers — this label buckets aggregator p95 separately).

        Args:
            client_id: Unique numeric ID of the client.
        """
        from service_metrics import instrument_call as _instrument_call

        async def _impl():
            return await _get_client_profile_impl(client_id)

        return await _instrument_call(
            "/rest/api/client",
            "GET",
            _impl,
            operation="aggregate_profile",
        )

    async def _get_client_profile_impl(client_id: int) -> dict:
        # Stage 103c: entity-specific composition lives in `resources/`.
        # This tool wrapper only adds `instrument_call` around the resource.
        from resources.client_profile import fetch as _fetch_client_profile
        return await _fetch_client_profile(client_id)

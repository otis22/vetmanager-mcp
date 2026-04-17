from fastmcp import FastMCP

from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update
from validators import LimitParam


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_goods(
        limit: LimitParam = 20,
        offset: int = 0,
        name: str = "",
        title: str = "",
        group_id: int = 0,
        is_active: bool | None = None,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List goods (products/services) in the clinic catalog.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            name: [DEPRECATED — use title=] Legacy server-side name query
                param. Kept for backward compatibility; will be removed.
            title: Filter by good title (LIKE match on the `title` field).
                Prefer this over `name` — it uses the standard filter API.
            group_id: Filter by product group ID.
            is_active: Filter by active status. None = no filter (default),
                True = only active, False = only inactive.
            sort: Optional sort spec.
            filter: Optional extra filter spec.
        """
        combined_filters: list[dict] = list(filter or [])
        if title:
            combined_filters.append(
                {"property": "title", "value": title, "operator": "LIKE"}
            )
        if group_id:
            combined_filters.append(
                {"property": "group_id", "value": group_id, "operator": "="}
            )
        if is_active is not None:
            combined_filters.append(
                {"property": "is_active", "value": 1 if is_active else 0, "operator": "="}
            )
        return await crud_list(
            "/rest/api/good", limit=limit, offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
            extra={"name": name},
        )

    @mcp.tool
    async def get_good_by_id(
        good_id: int,
    ) -> dict:
        """Get a good (product or service) by its unique ID.

        Args:
            good_id: Unique numeric ID of the good.
        """
        return await crud_get_by_id("/rest/api/good", good_id)

    @mcp.tool
    async def create_good(
        title: str,
        group_id: int = 0,
        unit_storage_id: int = 0,
        is_active: int = 1,
        code: str = "",
        is_for_sale: int = 1,
        prime_cost: float = 0.0,
        description: str = "",
    ) -> dict:
        """Create a new good (product or service) in the clinic catalog.

        Args:
            title: Name of the good or service (required).
            group_id: Product group ID (0 = no group).
            unit_storage_id: Unit of measurement ID (0 = default).
            is_active: Active status: 1 = active (default), 0 = inactive.
            code: Internal product code (optional).
            is_for_sale: Available for sale: 1 = yes (default), 0 = no.
            prime_cost: Cost price (0 = not set).
            description: Product description (optional).
        """
        payload: dict = {"title": title, "is_active": is_active, "is_for_sale": is_for_sale}
        if group_id:
            payload["group_id"] = group_id
        if unit_storage_id:
            payload["unit_storage_id"] = unit_storage_id
        if code:
            payload["code"] = code
        if prime_cost:
            payload["prime_cost"] = prime_cost
        if description:
            payload["description"] = description
        return await crud_create("/rest/api/good", payload)

    @mcp.tool
    async def update_good(
        good_id: int,
        title: str = "",
        group_id: int = 0,
        unit_storage_id: int = 0,
        is_active: int = -1,
        code: str = "",
        is_for_sale: int = -1,
        prime_cost: float = 0.0,
        description: str = "",
    ) -> dict:
        """Update an existing good (product or service).

        Args:
            good_id: ID of the good to update.
            title: Updated name (leave empty to keep current).
            group_id: Updated product group ID (0 = no change).
            unit_storage_id: Updated unit ID (0 = no change).
            is_active: Updated active status: 1 = active, 0 = inactive, -1 = no change.
            code: Updated product code.
            is_for_sale: Updated sale status: 1 = yes, 0 = no, -1 = no change.
            prime_cost: Updated cost price (0 = no change).
            description: Updated description.
        """
        payload: dict = {}
        if title:
            payload["title"] = title
        if group_id:
            payload["group_id"] = group_id
        if unit_storage_id:
            payload["unit_storage_id"] = unit_storage_id
        if is_active != -1:
            payload["is_active"] = is_active
        if code:
            payload["code"] = code
        if is_for_sale != -1:
            payload["is_for_sale"] = is_for_sale
        if prime_cost:
            payload["prime_cost"] = prime_cost
        if description:
            payload["description"] = description
        return await crud_update("/rest/api/good", good_id, payload)

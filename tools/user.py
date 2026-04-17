from fastmcp import FastMCP

from filters import eq as _filter_eq, like as _filter_like
from tools.crud_helpers import crud_list, crud_get_by_id, crud_update
from validators import LimitParam


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_users(
        limit: LimitParam = 20,
        offset: int = 0,
        name: str = "",
        position_id: int = 0,
        is_active: bool | None = True,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List users (staff/doctors) of the clinic.

        By default only active staff are returned. Pass is_active=False to
        list only inactive users, or is_active=None to include all.

        Name search covers BOTH last_name and first_name via two sequential
        requests merged by user id (Vetmanager filter language does not
        expose OR across properties in a first-class way). Result count is
        capped by `limit` after the merge.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000). Ignored when `name` is set
                (merge path starts from offset 0).
            name: Filter by staff name (LIKE match on last_name OR first_name).
            position_id: Filter by position ID (e.g. a doctor position).
            is_active: Active filter: True = active only (default),
                False = inactive only, None = all.
            sort: Optional sort spec.
            filter: Optional extra filter spec (merged with named filters).
        """
        base_filters: list = list(filter or [])
        if position_id:
            base_filters.append(_filter_eq("position_id", position_id))
        if is_active is not None:
            base_filters.append(_filter_eq("is_active", 1 if is_active else 0))

        if not name:
            return await crud_list(
                "/rest/api/user",
                limit=limit,
                offset=offset,
                sort=sort,
                filters=base_filters if base_filters else None,
            )

        # Name search: issue two parallel filter variants and merge by id.
        last_name_filters = base_filters + [_filter_like("last_name", name)]
        first_name_filters = base_filters + [_filter_like("first_name", name)]

        last_name_resp = await crud_list(
            "/rest/api/user",
            limit=limit,
            offset=0,
            sort=sort,
            filters=last_name_filters,
        )
        first_name_resp = await crud_list(
            "/rest/api/user",
            limit=limit,
            offset=0,
            sort=sort,
            filters=first_name_filters,
        )

        def _extract_users(resp: dict) -> list[dict]:
            data = resp.get("data", {}) if isinstance(resp, dict) else {}
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("user") or data.get("users") or []
            return []

        seen_ids: set = set()
        merged: list[dict] = []
        for user in _extract_users(last_name_resp) + _extract_users(first_name_resp):
            uid = user.get("id")
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            merged.append(user)
            if len(merged) >= limit:
                break

        return {"success": True, "data": {"user": merged, "totalCount": len(merged)}}

    @mcp.tool
    async def get_user_by_id(
        user_id: int,
    ) -> dict:
        """Get a clinic user (staff member) by their unique ID.

        Args:
            user_id: Unique numeric ID of the user.
        """
        return await crud_get_by_id("/rest/api/user", user_id)

    @mcp.tool
    async def update_user(
        user_id: int,
        last_name: str = "",
        first_name: str = "",
        middle_name: str = "",
        email: str = "",
        phone: str = "",
        cell_phone: str = "",
        position_id: int = 0,
        role_id: int = 0,
        is_active: int = -1,
    ) -> dict:
        """Update an existing user (staff member) record.

        Note: Vetmanager API does not allow creating or deleting users via REST.

        Args:
            user_id: ID of the user to update.
            last_name: New last name (leave empty to keep current).
            first_name: New first name (leave empty to keep current).
            middle_name: New middle name (leave empty to keep current).
            email: New email address (leave empty to keep current).
            phone: New phone number (leave empty to keep current).
            cell_phone: New cell phone number (leave empty to keep current).
            position_id: New position ID (0 = no change).
            role_id: New role ID (0 = no change).
            is_active: Set active status: 1 = active, 0 = inactive, -1 = no change.
        """
        payload: dict = {}
        if last_name:
            payload["last_name"] = last_name
        if first_name:
            payload["first_name"] = first_name
        if middle_name:
            payload["middle_name"] = middle_name
        if email:
            payload["email"] = email
        if phone:
            payload["phone"] = phone
        if cell_phone:
            payload["cell_phone"] = cell_phone
        if position_id:
            payload["position_id"] = position_id
        if role_id:
            payload["role_id"] = role_id
        if is_active != -1:
            payload["is_active"] = is_active
        return await crud_update("/rest/api/user", user_id, payload)

from fastmcp import FastMCP

from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_users(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List users (staff) of the clinic.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await vc.get("/rest/api/user", params=params)

    @mcp.tool
    async def get_user_by_id(
        user_id: int,
    ) -> dict:
        """Get a clinic user (staff member) by their unique ID.

        Args:
            user_id: Unique numeric ID of the user.
        """
        vc = VetmanagerClient()
        return await vc.get(f"/rest/api/user/{user_id}")

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
        vc = VetmanagerClient()
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
        return await vc.put(f"/rest/api/user/{user_id}", json=payload)

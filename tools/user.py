from fastmcp import FastMCP

from validators import build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_users(
        limit: int = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List users (staff) of the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
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
            domain: Clinic subdomain.
            api_key: REST API key.
            user_id: Unique numeric ID of the user.
        """
        vc = VetmanagerClient()
        return await vc.get(f"/rest/api/user/{user_id}")

from fastmcp import FastMCP

from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_users(
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """List users (staff) of the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
        """
        validate_list_params(limit, offset)
        vc = VetmanagerClient()
        return await vc.get("/rest/api/user", params={"limit": limit, "offset": offset})

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

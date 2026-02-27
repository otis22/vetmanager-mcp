from fastmcp import FastMCP

from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_users(
        domain: str,
        api_key: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """List users (staff) of the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        vc = VetmanagerClient(domain, api_key)
        return await vc.get("/rest/api/user", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_user_by_id(
        domain: str,
        api_key: str,
        user_id: int,
    ) -> dict:
        """Get a clinic user (staff member) by their unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            user_id: Unique numeric ID of the user.
        """
        vc = VetmanagerClient(domain, api_key)
        return await vc.get(f"/rest/api/user/{user_id}")

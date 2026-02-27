from fastmcp import FastMCP

from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_goods(
        domain: str,
        api_key: str,
        limit: int = 20,
        offset: int = 0,
        name: str = "",
    ) -> dict:
        """List goods (products/services) in the clinic catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            name: Filter by good name (partial match, optional).
        """
        validate_list_params(limit, offset)
        vc = VetmanagerClient(domain, api_key)
        params: dict = {"limit": limit, "offset": offset}
        if name:
            params["name"] = name
        return await vc.get("/rest/api/good", params=params)

    @mcp.tool
    async def get_good_by_id(
        domain: str,
        api_key: str,
        good_id: int,
    ) -> dict:
        """Get a good (product or service) by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            good_id: Unique numeric ID of the good.
        """
        vc = VetmanagerClient(domain, api_key)
        return await vc.get(f"/rest/api/good/{good_id}")

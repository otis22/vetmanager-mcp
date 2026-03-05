from fastmcp import FastMCP

from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_goods(
        limit: LimitParam = 20,
        offset: int = 0,
        name: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List goods (products/services) in the clinic catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            name: Filter by good name (partial match, optional).
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"name": name},
        )
        return await vc.get("/rest/api/good", params=params)

    @mcp.tool
    async def get_good_by_id(
        good_id: int,
    ) -> dict:
        """Get a good (product or service) by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            good_id: Unique numeric ID of the good.
        """
        vc = VetmanagerClient()
        return await vc.get(f"/rest/api/good/{good_id}")

"""Operational entity tools: Clinics, Timesheet, Properties, AnonymousClient."""

from fastmcp import FastMCP
from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clinics(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List clinic branches in the system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/clinics", params=params)

    @mcp.tool
    async def get_clinic_by_id(clinic_id: int) -> dict:
        """Get a clinic branch by its unique ID.

        Args:
            clinic_id: Unique numeric ID of the clinic.
        """
        return await VetmanagerClient().get(f"/rest/api/clinics/{clinic_id}")

    @mcp.tool
    async def get_timesheets(
        limit: LimitParam = 20,
        offset: int = 0,
        user_id: int = 0,
        date: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List staff work schedule entries (timesheets).

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            user_id: Filter by staff user ID (0 = no filter).
            date: Filter by date in YYYY-MM-DD format (optional).
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"userId": user_id, "date": date},
        )
        return await vc.get("/rest/api/timesheet", params=params)

    @mcp.tool
    async def get_timesheet_by_id(timesheet_id: int) -> dict:
        """Get a timesheet entry by its unique ID.

        Args:
            timesheet_id: Unique numeric ID of the timesheet entry.
        """
        return await VetmanagerClient().get(f"/rest/api/timesheet/{timesheet_id}")

    @mcp.tool
    async def get_properties(
        limit: LimitParam = 50,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List system configuration properties of the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/properties", params=params)

    @mcp.tool
    async def get_anonymous_clients(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List anonymous (walk-in) client records in the system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/user/anonymousList", params=params)

"""Operational entity tools: Clinics, Timesheet, Properties, AnonymousClient."""

from fastmcp import FastMCP
from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clinics(limit: int = 20, offset: int = 0) -> dict:
        """List clinic branches in the system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/clinics", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_clinic_by_id(clinic_id: int) -> dict:
        """Get a clinic branch by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            clinic_id: Unique numeric ID of the clinic.
        """
        return await VetmanagerClient().get(f"/rest/api/clinics/{clinic_id}")

    @mcp.tool
    async def get_timesheets(limit: int = 20, offset: int = 0, user_id: int = 0, date: str = "") -> dict:
        """List staff work schedule entries (timesheets).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            user_id: Filter by staff user ID (0 = no filter).
            date: Filter by date in YYYY-MM-DD format (optional).
        """
        vc = VetmanagerClient()
        validate_list_params(limit, offset)
        params: dict = {"limit": limit, "offset": offset}
        if user_id:
            params["userId"] = user_id
        if date:
            params["date"] = date
        return await vc.get("/rest/api/timesheet", params=params)

    @mcp.tool
    async def get_timesheet_by_id(timesheet_id: int) -> dict:
        """Get a timesheet entry by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            timesheet_id: Unique numeric ID of the timesheet entry.
        """
        return await VetmanagerClient().get(f"/rest/api/timesheet/{timesheet_id}")

    @mcp.tool
    async def get_properties(limit: int = 50, offset: int = 0) -> dict:
        """List system configuration properties of the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/properties", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_anonymous_clients(limit: int = 20, offset: int = 0) -> dict:
        """List anonymous (walk-in) client records in the system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/user/anonymousList", params={"limit": limit, "offset": offset})

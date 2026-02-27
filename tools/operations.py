"""Operational entity tools: Clinics, Timesheet, Properties, AnonymousClient."""

from fastmcp import FastMCP
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clinics(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List clinic branches in the system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await VetmanagerClient(domain, api_key).get("/rest/api/clinics", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_clinic_by_id(domain: str, api_key: str, clinic_id: int) -> dict:
        """Get a clinic branch by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            clinic_id: Unique numeric ID of the clinic.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/clinics/{clinic_id}")

    @mcp.tool
    async def get_timesheets(domain: str, api_key: str, limit: int = 20, offset: int = 0, user_id: int = 0, date: str = "") -> dict:
        """List staff work schedule entries (timesheets).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            user_id: Filter by staff user ID (0 = no filter).
            date: Filter by date in YYYY-MM-DD format (optional).
        """
        vc = VetmanagerClient(domain, api_key)
        params: dict = {"limit": limit, "offset": offset}
        if user_id:
            params["userId"] = user_id
        if date:
            params["date"] = date
        return await vc.get("/rest/api/timesheet", params=params)

    @mcp.tool
    async def get_timesheet_by_id(domain: str, api_key: str, timesheet_id: int) -> dict:
        """Get a timesheet entry by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            timesheet_id: Unique numeric ID of the timesheet entry.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/timesheet/{timesheet_id}")

    @mcp.tool
    async def get_properties(domain: str, api_key: str, limit: int = 50, offset: int = 0) -> dict:
        """List system configuration properties of the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await VetmanagerClient(domain, api_key).get("/rest/api/properties", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_anonymous_clients(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List anonymous (walk-in) client records in the system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await VetmanagerClient(domain, api_key).get("/rest/api/user/anonymousList", params={"limit": limit, "offset": offset})

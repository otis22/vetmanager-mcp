"""Operational entity tools: Clinics, Timesheet, Properties, AnonymousClient, Messages."""

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field
from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient

UserIdsParam = Annotated[
    list[int],
    Field(min_length=1, description="Target user IDs (at least one user ID)."),
]

RolesParam = Annotated[
    list[str],
    Field(min_length=1, description="Target role names (at least one role)."),
]


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
    async def create_timesheet(
        doctor_id: int,
        begin_datetime: str,
        end_datetime: str,
        clinic_id: int,
        title: str = "",
        type: str = "",
    ) -> dict:
        """Create a new work schedule entry (timesheet) for a staff member.

        Args:
            doctor_id: ID of the staff member/doctor.
            begin_datetime: Start date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            end_datetime: End date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            clinic_id: ID of the clinic branch.
            title: Schedule entry title/label (optional).
            type: Schedule type (optional).
        """
        vc = VetmanagerClient()
        payload: dict = {
            "doctor_id": doctor_id,
            "begin_datetime": begin_datetime,
            "end_datetime": end_datetime,
            "clinic_id": clinic_id,
        }
        if title:
            payload["title"] = title
        if type:
            payload["type"] = type
        return await vc.post("/rest/api/timesheet", json=payload)

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

    @mcp.tool
    async def send_message_to_all(
        message: str,
        campaign: str,
    ) -> dict:
        """Send an in-app notification to all clinic users."""
        payload = {"message": message, "campaign": campaign}
        return await VetmanagerClient().post("/rest/api/messages/all", json=payload)

    @mcp.tool
    async def send_message_to_users(
        message: str,
        campaign: str,
        user_ids: UserIdsParam,
    ) -> dict:
        """Send an in-app notification to specific users by ID."""
        payload = {
            "message": message,
            "campaign": campaign,
            "user_ids": user_ids,
        }
        return await VetmanagerClient().post("/rest/api/messages/users", json=payload)

    @mcp.tool
    async def get_message_reports(
        limit: LimitParam = 20,
        offset: int = 0,
        campaign: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List in-app notification delivery reports and campaign stats."""
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"campaign": campaign},
        )
        return await VetmanagerClient().get("/rest/api/messages/reports", params=params)

    @mcp.tool
    async def send_message_to_roles(
        message: str,
        campaign: str,
        roles: RolesParam,
    ) -> dict:
        """Send an in-app notification to all users with the specified roles."""
        payload = {
            "message": message,
            "campaign": campaign,
            "roles": roles,
        }
        return await VetmanagerClient().post("/rest/api/messages/roles", json=payload)

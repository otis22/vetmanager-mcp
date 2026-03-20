import json
from fastmcp import FastMCP

from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_admissions(
        limit: LimitParam = 20,
        offset: int = 0,
        date: str = "",
        status: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List clinic admissions (appointments/visits).

        To get today's admissions pass date="YYYY-MM-DD" (e.g. "2026-03-06").
        The date filter is applied via the Vetmanager API filter parameter so only
        matching records are returned — no client-side filtering needed.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            date: Filter by exact date in YYYY-MM-DD format (optional).
                  When provided, only admissions whose admission_date starts with
                  this date are returned.
            status: Filter by admission status, e.g. 'assigned', 'accepted',
                    'booked', 'canceled' (optional).
            sort: Sort specification, e.g. [{"property": "admission_date", "direction": "ASC"}].
            filter: Additional filter conditions (merged with date/status filters).
        """
        vc = VetmanagerClient()

        # Build filter list: merge explicit filters with date and status shortcuts.
        combined_filters: list[dict] = list(filter or [])
        if date:
            combined_filters.append(
                {"property": "admission_date", "value": date, "operator": "like"}
            )
        if status:
            combined_filters.append(
                {"property": "status", "value": status, "operator": "="}
            )

        # Default sort by admission_date ASC so today's records appear in time order.
        if sort is None and date:
            sort = [{"property": "admission_date", "direction": "ASC"}]

        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
        )
        return await vc.get("/rest/api/admission", params=params)

    @mcp.tool
    async def get_admission_by_id(
        admission_id: int,
    ) -> dict:
        """Get an admission (visit/appointment) by its unique ID.

        Args:
            admission_id: Unique numeric ID of the admission.
        """
        vc = VetmanagerClient()
        return await vc.get(f"/rest/api/admission/{admission_id}")

    @mcp.tool
    async def create_admission(
        pet_id: int,
        client_id: int,
        doctor_id: int,
        date: str,
        reason: str = "",
        status: str = "assigned",
    ) -> dict:
        """Schedule a new admission (appointment) for a pet.

        Args:
            pet_id: ID of the pet being admitted.
            client_id: ID of the pet's owner.
            doctor_id: ID of the attending veterinarian.
            date: Appointment date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            reason: Reason for the visit (optional).
            status: Admission status: 'assigned' (default), 'booked', 'accepted'.
        """
        vc = VetmanagerClient()
        payload: dict = {
            "pet_id": pet_id,
            "client_id": client_id,
            "doctor_id": doctor_id,
            "date": date,
            "status": status,
        }
        if reason:
            payload["reason"] = reason
        return await vc.post("/rest/api/admission", json=payload)

    @mcp.tool
    async def update_admission(
        admission_id: int,
        date: str = "",
        doctor_id: int = 0,
        reason: str = "",
        status: str = "",
    ) -> dict:
        """Update an existing admission (appointment) record.

        Args:
            admission_id: ID of the admission to update.
            date: New date/time in ISO 8601 format (leave empty to keep current).
            doctor_id: New doctor ID (0 = no change).
            reason: Updated reason for the visit.
            status: New status value (e.g. 'assigned', 'accepted', 'booked', 'canceled').
        """
        vc = VetmanagerClient()
        payload: dict = {}
        if date:
            payload["date"] = date
        if doctor_id:
            payload["doctor_id"] = doctor_id
        if reason:
            payload["reason"] = reason
        if status:
            payload["status"] = status
        return await vc.put(f"/rest/api/admission/{admission_id}", json=payload)

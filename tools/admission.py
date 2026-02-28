from fastmcp import FastMCP

from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_admissions(
        limit: int = 20,
        offset: int = 0,
        date: str = "",
    ) -> dict:
        """List clinic admissions (appointments/visits).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            date: Filter by date in YYYY-MM-DD format (optional).
        """
        validate_list_params(limit, offset)
        vc = VetmanagerClient()
        params: dict = {"limit": limit, "offset": offset}
        if date:
            params["date"] = date
        return await vc.get("/rest/api/admission", params=params)

    @mcp.tool
    async def get_admission_by_id(
        admission_id: int,
    ) -> dict:
        """Get an admission (visit/appointment) by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
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
    ) -> dict:
        """Schedule a new admission (appointment) for a pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet being admitted.
            client_id: ID of the pet's owner.
            doctor_id: ID of the attending veterinarian.
            date: Appointment date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            reason: Reason for the visit (optional).
        """
        vc = VetmanagerClient()
        payload: dict = {
            "pet_id": pet_id,
            "client_id": client_id,
            "doctor_id": doctor_id,
            "date": date,
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
            domain: Clinic subdomain.
            api_key: REST API key.
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

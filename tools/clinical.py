"""Clinical entity tools: Hospital, HospitalBlock, Diagnoses."""

from fastmcp import FastMCP
from filters import eq as _filter_eq
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update
from validators import LimitParam
from vm_datetime import normalize_vm_datetime


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_hospitalizations(
        limit: LimitParam = 20,
        offset: int = 0,
        pet_id: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List hospitalizations (inpatient stays) in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            pet_id: Filter by pet ID (0 = no filter).
        """
        combined_filters: list = list(filter or [])
        if pet_id:
            combined_filters.append(_filter_eq("patient_id", pet_id))
        return await crud_list(
            "/rest/api/hospital", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_hospitalization_by_id(hospital_id: int) -> dict:
        """Get a hospitalization record by its unique ID.

        Args:
            hospital_id: Unique numeric ID of the hospitalization record.
        """
        return await crud_get_by_id("/rest/api/hospital", hospital_id)

    @mcp.tool
    async def create_hospitalization(pet_id: int, doctor_id: int, date_in: str, block_id: int = 0, description: str = "") -> dict:
        """Register a new hospitalization (inpatient admission) for a pet.

        Args:
            pet_id: ID of the pet being hospitalized.
            doctor_id: ID of the responsible veterinarian.
            date_in: Admission date/time. Accepts VM datetime
                (YYYY-MM-DD HH:MM:SS) or local ISO datetime without timezone;
                sends VM format to the API.
            block_id: ID of the hospital block/ward (0 if not specified).
            description: Clinical notes or reason for hospitalization.
        """
        payload: dict = {
            "patient_id": pet_id,
            "doctor_id": doctor_id,
            "date_in": normalize_vm_datetime(date_in, field_name="date_in"),
        }
        if block_id:
            payload["hospital_block_id"] = block_id
        if description:
            payload["description"] = description
        return await crud_create("/rest/api/hospital", payload)

    @mcp.tool
    async def update_hospitalization(
        hospital_id: int,
        date_out: str = "",
        description: str = "",
        status: str = "",
        block_id: int = 0,
    ) -> dict:
        """Update an existing hospitalization record.

        Note: Vetmanager API does not allow deleting hospitalizations via REST.

        Args:
            hospital_id: ID of the hospitalization record to update.
            date_out: Discharge date/time. Accepts VM datetime
                (YYYY-MM-DD HH:MM:SS) or local ISO datetime without timezone;
                sends VM format to the API. Leave empty to keep current.
            description: Updated clinical notes (leave empty to keep current).
            status: Updated status (leave empty to keep current).
            block_id: New hospital block/ward ID (0 = no change).
        """
        payload: dict = {}
        if date_out:
            payload["date_out"] = normalize_vm_datetime(date_out, field_name="date_out")
        if description:
            payload["description"] = description
        if status:
            payload["status"] = status
        if block_id:
            payload["hospital_block_id"] = block_id
        return await crud_update("/rest/api/hospital", hospital_id, payload)

    @mcp.tool
    async def get_hospital_blocks(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List hospital blocks/wards available in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/HospitalBlock", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_hospital_block_by_id(block_id: int) -> dict:
        """Get a hospital block/ward by its unique ID.

        Args:
            block_id: Unique numeric ID of the hospital block.
        """
        return await crud_get_by_id("/rest/api/HospitalBlock", block_id)

    @mcp.tool
    async def get_diagnoses(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List all diagnoses recorded across all medical cards.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/MedicalCards/AllDiagnoses", limit=limit, offset=offset, sort=sort, filters=filter,
        )

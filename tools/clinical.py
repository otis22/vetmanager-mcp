"""Clinical entity tools: Hospital, HospitalBlock, Diagnoses."""

from fastmcp import FastMCP
from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


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
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            pet_id: Filter by pet ID (0 = no filter).
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"petId": pet_id},
        )
        return await vc.get("/rest/api/hospital", params=params)

    @mcp.tool
    async def get_hospitalization_by_id(hospital_id: int) -> dict:
        """Get a hospitalization record by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            hospital_id: Unique numeric ID of the hospitalization record.
        """
        return await VetmanagerClient().get(f"/rest/api/hospital/{hospital_id}")

    @mcp.tool
    async def create_hospitalization(pet_id: int, doctor_id: int, date_in: str, block_id: int = 0, description: str = "") -> dict:
        """Register a new hospitalization (inpatient admission) for a pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet being hospitalized.
            doctor_id: ID of the responsible veterinarian.
            date_in: Admission date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            block_id: ID of the hospital block/ward (0 if not specified).
            description: Clinical notes or reason for hospitalization.
        """
        vc = VetmanagerClient()
        payload: dict = {"petId": pet_id, "doctorId": doctor_id, "dateIn": date_in}
        if block_id:
            payload["blockId"] = block_id
        if description:
            payload["description"] = description
        return await vc.post("/rest/api/hospital", json=payload)

    @mcp.tool
    async def get_hospital_blocks(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List hospital blocks/wards available in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/HospitalBlock", params=params)

    @mcp.tool
    async def get_hospital_block_by_id(block_id: int) -> dict:
        """Get a hospital block/ward by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            block_id: Unique numeric ID of the hospital block.
        """
        return await VetmanagerClient().get(f"/rest/api/HospitalBlock/{block_id}")

    @mcp.tool
    async def get_diagnoses(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List all diagnoses recorded across all medical cards.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
        )
        return await VetmanagerClient().get("/rest/api/MedicalCards/AllDiagnoses", params=params)

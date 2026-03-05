from fastmcp import FastMCP

from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_medical_cards(
        pet_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List medical card records for a specific pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet whose records to retrieve.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"pet_id": pet_id},
        )
        return await vc.get("/rest/api/medicalcard", params=params)

    @mcp.tool
    async def get_medical_card_by_id(
        card_id: int,
    ) -> dict:
        """Get a medical card record by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            card_id: Unique numeric ID of the medical card record.
        """
        vc = VetmanagerClient()
        return await vc.get(f"/rest/api/medicalcard/{card_id}")

    @mcp.tool
    async def create_medical_card(
        pet_id: int,
        doctor_id: int,
        date: str,
        description: str,
        diagnosis: str = "",
        treatment: str = "",
    ) -> dict:
        """Add a new medical card record for a pet.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet.
            doctor_id: ID of the veterinarian creating the record.
            date: Record date in YYYY-MM-DD format.
            description: Clinical description / anamnesis.
            diagnosis: Diagnosis text (optional).
            treatment: Prescribed treatment (optional).
        """
        vc = VetmanagerClient()
        payload: dict = {
            "pet_id": pet_id,
            "doctor_id": doctor_id,
            "date": date,
            "description": description,
        }
        if diagnosis:
            payload["diagnosis"] = diagnosis
        if treatment:
            payload["treatment"] = treatment
        return await vc.post("/rest/api/medicalcard", json=payload)

    @mcp.tool
    async def update_medical_card(
        card_id: int,
        description: str = "",
        diagnosis: str = "",
        treatment: str = "",
    ) -> dict:
        """Update an existing medical card record.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            card_id: ID of the medical card record to update.
            description: Updated clinical description/anamnesis.
            diagnosis: Updated diagnosis text.
            treatment: Updated treatment notes.
        """
        vc = VetmanagerClient()
        payload: dict = {}
        if description:
            payload["description"] = description
        if diagnosis:
            payload["diagnosis"] = diagnosis
        if treatment:
            payload["treatment"] = treatment
        return await vc.put(f"/rest/api/MedicalCards/{card_id}", json=payload)

    @mcp.tool
    async def get_vaccinations(
        pet_id: int,
        limit: LimitParam = 50,
    ) -> dict:
        """Get all vaccination records for a pet.

        Returns a list of vaccinations including vaccine name, date administered,
        and the scheduled next vaccination date.

        Args:
            pet_id: Unique numeric ID of the pet.
            limit: Max number of records to return (1–100, default 50).
        """
        vc = VetmanagerClient()
        params: dict = {"pet_id": pet_id, "limit": limit}
        result = await vc.get("/rest/api/MedicalCards/Vaccinations", params=params)
        records = result.get("data", {}).get("medicalcards", [])
        return {
            "pet_id": pet_id,
            "total": len(records),
            "vaccinations": [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "date": r.get("date"),
                    "date_nexttime": r.get("date_nexttime"),
                    "vaccine_id": r.get("vaccine_id"),
                    "medcard_id": r.get("medcard_id"),
                    "doza_value": r.get("doza_value"),
                    "next_admission_id": r.get("next_admission_id"),
                    "pet_age_at_time_vaccination": r.get("pet_age_at_time_vaccination"),
                }
                for r in records
            ],
        }

import json
from fastmcp import FastMCP

from tools.crud_helpers import crud_get_by_id, crud_create, crud_update
from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient

# The correct Vetmanager REST endpoint for medical cards is /rest/api/MedicalCards
# (capital M and C, plural). The response key is "medicalCards" (camelCase).
# The old lowercase /rest/api/medicalcard returns 404 on all known installations.
_MC_ENDPOINT = "/rest/api/MedicalCards"
_MC_KEY = "medicalCards"


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
            pet_id: ID of the pet whose records to retrieve.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
        """
        vc = VetmanagerClient()
        # patient_id filter is required — pet_id param alone is ignored by the API
        extra_filters: list[dict] = []
        if filter:
            extra_filters = filter if isinstance(filter, list) else []
        combined_filter = json.dumps(
            [{"property": "patient_id", "value": str(pet_id), "operator": "="}]
            + extra_filters,
            separators=(",", ":"),
        )
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=None,  # handled manually above
        )
        params["filter"] = combined_filter
        result = await vc.get(_MC_ENDPOINT, params=params)
        # Normalise response: expose records under both "medicalCards" and "medicalcards"
        # so that existing assistant code that checks either key keeps working.
        data = result.get("data", {})
        if isinstance(data, dict) and _MC_KEY in data and "medicalcards" not in data:
            data["medicalcards"] = data[_MC_KEY]
        return result

    @mcp.tool
    async def get_medical_cards_by_client_id(
        client_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
    ) -> dict:
        """List all medical card records for all pets belonging to a client.

        Use this tool when the user asks to see medical cards / history for a
        client identified by their client ID (not a pet ID).  The tool fetches
        all pets of the client first, then returns their medical cards in a
        single aggregated response.

        Args:
            client_id: Unique numeric ID of the client (owner).
            limit: Max records per pet to return (1–100, default 20).
            offset: Pagination offset (0–10000).
        """
        vc = VetmanagerClient()

        # Step 1: get all pets of the client.
        # Pet entity FK to client is `owner_id` (migrated stage 77.4;
        # legacy `client_id` filter returns empty silently).
        pet_filter = json.dumps(
            [{"property": "owner_id", "value": str(client_id), "operator": "="}],
            separators=(",", ":"),
        )
        pets_resp = await vc.get("/rest/api/pet", params={"filter": pet_filter, "limit": 100})
        pets_data = pets_resp.get("data", {})
        pets = pets_data.get("pet", []) if isinstance(pets_data, dict) else []

        if not pets:
            return {
                "success": True,
                "client_id": client_id,
                "pets_count": 0,
                "medical_cards": [],
                "message": "No pets found for this client.",
            }

        # Step 2: fetch medical cards for ALL pets in a single IN-batched call.
        pet_ids = [pet.get("id") for pet in pets if pet.get("id")]
        pet_by_id = {pet.get("id"): pet for pet in pets if pet.get("id")}

        if not pet_ids:
            # Pets returned without usable ids — treat as no medical cards.
            return {
                "success": True,
                "client_id": client_id,
                "pets_count": len(pets),
                "medical_cards_count": 0,
                "medical_cards": [],
            }

        mc_filter = json.dumps(
            [{"property": "patient_id", "value": pet_ids, "operator": "IN"}],
            separators=(",", ":"),
        )
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=None,
        )
        params["filter"] = mc_filter
        cards_resp = await vc.get(_MC_ENDPOINT, params=params)
        cards_data = cards_resp.get("data", {})
        if isinstance(cards_data, dict):
            all_cards = (
                cards_data.get(_MC_KEY)
                or cards_data.get("medicalcards")
                or []
            )
        else:
            all_cards = []
        for card in all_cards:
            pid = card.get("patient_id")
            pet = pet_by_id.get(pid) or pet_by_id.get(int(pid) if isinstance(pid, str) and pid.isdigit() else pid)
            if pet:
                card["_pet_alias"] = pet.get("alias") or pet.get("name") or str(pid)
                card["_pet_id"] = pid

        return {
            "success": True,
            "client_id": client_id,
            "pets_count": len(pets),
            "medical_cards_count": len(all_cards),
            "medical_cards": all_cards,
        }

    @mcp.tool
    async def get_medical_card_by_id(
        card_id: int,
    ) -> dict:
        """Get a medical card record by its unique ID.

        Args:
            card_id: Unique numeric ID of the medical card record.
        """
        return await crud_get_by_id(_MC_ENDPOINT, card_id)

    @mcp.tool
    async def create_medical_card(
        patient_id: int,
        doctor_id: int,
        date_create: str,
        description: str = "",
        diagnosis: str = "",
        treatment: str = "",
        recomendation: str = "",
        clinic_id: int = 0,
        admission_type: str = "",
        meet_result_id: int = 0,
        weight: float = 0.0,
        temperature: float = 0.0,
    ) -> dict:
        """Add a new medical card record for a pet.

        Use patient_id (pet ID) to identify the animal.  All other fields are
        optional but should be filled in when provided by the user.

        Args:
            patient_id: ID of the pet (patient).  Also accepted as pet_id.
            doctor_id: ID of the veterinarian creating the record.
            date_create: Record date in YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format.
            description: Clinical description / anamnesis (optional).
            diagnosis: Diagnosis text (optional).
            treatment: Prescribed treatment (optional).
            recomendation: Recommendations for the owner (optional).
            clinic_id: ID of the clinic branch (optional, 0 = default).
            admission_type: Type of admission, e.g. "Взятие анализа",
                            "Первичный прием", "Плановый осмотр" (optional).
            meet_result_id: ID of the visit result from the combo manual (optional, 0 = none).
            weight: Animal weight in kg at the time of visit (optional, 0 = not recorded).
            temperature: Animal body temperature in °C (optional, 0 = not recorded).
        """
        payload: dict = {
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "date_create": date_create,
        }
        if description:
            payload["description"] = description
        if diagnosis:
            payload["diagnos"] = diagnosis  # API field name is "diagnos"
        if treatment:
            payload["treatment"] = treatment
        if recomendation:
            payload["recomendation"] = recomendation
        if clinic_id:
            payload["clinic_id"] = clinic_id
        if admission_type:
            payload["admission_type"] = admission_type
        if meet_result_id:
            payload["meet_result_id"] = meet_result_id
        if weight:
            payload["weight"] = weight
        if temperature:
            payload["temperature"] = temperature
        return await crud_create(_MC_ENDPOINT, payload)

    @mcp.tool
    async def update_medical_card(
        card_id: int,
        description: str = "",
        diagnosis: str = "",
        treatment: str = "",
        recomendation: str = "",
        weight: float = 0.0,
        temperature: float = 0.0,
    ) -> dict:
        """Update an existing medical card record.

        Args:
            card_id: ID of the medical card record to update.
            description: Updated clinical description/anamnesis.
            diagnosis: Updated diagnosis text.
            treatment: Updated treatment notes.
            recomendation: Updated recommendations for the owner.
            weight: Updated animal weight in kg (0 = no change).
            temperature: Updated body temperature in °C (0 = no change).
        """
        payload: dict = {}
        if description:
            payload["description"] = description
        if diagnosis:
            payload["diagnos"] = diagnosis  # API field name is "diagnos"
        if treatment:
            payload["treatment"] = treatment
        if recomendation:
            payload["recomendation"] = recomendation
        if weight:
            payload["weight"] = weight
        if temperature:
            payload["temperature"] = temperature
        return await crud_update(_MC_ENDPOINT, card_id, payload)

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

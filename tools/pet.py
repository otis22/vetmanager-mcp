from fastmcp import FastMCP

from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_pets(
        limit: LimitParam = 20,
        offset: int = 0,
        client_id: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List pets in the clinic, optionally filtered by owner.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            client_id: Filter pets by owner's client ID (0 = no filter).
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"client_id": client_id},
        )
        return await vc.get("/rest/api/pet", params=params)

    @mcp.tool
    async def get_pet_by_id(
        pet_id: int,
    ) -> dict:
        """Get a pet by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: Unique numeric ID of the pet.
        """
        vc = VetmanagerClient()
        return await vc.get(f"/rest/api/pet/{pet_id}")

    @mcp.tool
    async def create_pet(
        alias: str,
        client_id: int,
        type_id: int = 0,
        breed_id: int = 0,
        birthday: str = "",
        note: str = "",
    ) -> dict:
        """Register a new pet for a client.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            alias: Pet's name/alias.
            client_id: ID of the owner (client).
            type_id: Animal type ID (species). Use 0 if unknown.
            breed_id: Breed ID. Use 0 if unknown.
            birthday: Date of birth in YYYY-MM-DD format (optional).
            note: Additional notes about the pet.
        """
        vc = VetmanagerClient()
        payload: dict = {"alias": alias, "client_id": client_id}
        if type_id:
            payload["type_id"] = type_id
        if breed_id:
            payload["breed_id"] = breed_id
        if birthday:
            payload["birthday"] = birthday
        if note:
            payload["note"] = note
        return await vc.post("/rest/api/pet", json=payload)

    @mcp.tool
    async def update_pet(
        pet_id: int,
        alias: str = "",
        type_id: int = 0,
        breed_id: int = 0,
        birthday: str = "",
        note: str = "",
    ) -> dict:
        """Update an existing pet's details.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: ID of the pet to update.
            alias: New pet name/alias (leave empty to keep current).
            type_id: New animal type ID (0 = no change).
            breed_id: New breed ID (0 = no change).
            birthday: Date of birth in YYYY-MM-DD format (optional).
            note: Updated notes about the pet.
        """
        vc = VetmanagerClient()
        payload: dict = {}
        if alias:
            payload["alias"] = alias
        if type_id:
            payload["type_id"] = type_id
        if breed_id:
            payload["breed_id"] = breed_id
        if birthday:
            payload["birthday"] = birthday
        if note:
            payload["note"] = note
        return await vc.put(f"/rest/api/pet/{pet_id}", json=payload)

    @mcp.tool
    async def get_pet_profile(
        pet_id: int,
    ) -> dict:
        """Get a comprehensive profile for a pet in one call.

        Aggregates:
        - Full pet record (with breed and type data)
        - Last 5 medical card records
        - All vaccination records (date, next vaccination date, vaccine name)
        - Computed last_vaccination_date and next_vaccination_date

        Args:
            pet_id: Unique numeric ID of the pet.
        """
        import json as _json

        vc = VetmanagerClient()

        pet_resp = await vc.get(f"/rest/api/pet/{pet_id}")
        pet_data = pet_resp.get("data", {}).get("pet", {})

        mc_filter = _json.dumps(
            [{"property": "patient_id", "value": str(pet_id)}],
            separators=(",", ":"),
        )
        mc_sort = _json.dumps(
            [{"property": "id", "direction": "DESC"}],
            separators=(",", ":"),
        )
        mc_resp = await vc.get(
            "/rest/api/medicalcard",
            params={"filter": mc_filter, "sort": mc_sort, "limit": 5},
        )
        medical_cards = mc_resp.get("data", {}).get("medicalcard", [])

        vacc_resp = await vc.get(
            "/rest/api/MedicalCards/Vaccinations",
            params={"pet_id": pet_id, "limit": 100},
        )
        vaccinations_raw = vacc_resp.get("data", {}).get("medicalcards", [])
        vaccinations = [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "date": r.get("date"),
                "date_nexttime": r.get("date_nexttime"),
                "vaccine_id": r.get("vaccine_id"),
                "medcard_id": r.get("medcard_id"),
            }
            for r in vaccinations_raw
        ]

        sorted_vacc = sorted(
            vaccinations,
            key=lambda r: r.get("date") or "",
            reverse=True,
        )
        last_vaccination_date: str | None = None
        next_vaccination_date: str | None = None
        if sorted_vacc:
            last_vacc = sorted_vacc[0]
            last_vaccination_date = (last_vacc.get("date") or "").split(" ")[0] or None
            next_raw = last_vacc.get("date_nexttime") or ""
            next_vaccination_date = next_raw.strip() or None

        return {
            "pet": pet_data,
            "last_medical_cards": medical_cards,
            "vaccinations": vaccinations,
            "last_vaccination_date": last_vaccination_date,
            "next_vaccination_date": next_vaccination_date,
        }

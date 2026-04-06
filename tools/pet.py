from datetime import date, timedelta

from fastmcp import FastMCP

from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete, paginate_all
from validators import LimitParam
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
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            client_id: Filter pets by owner's client ID (0 = no filter).
        """
        return await crud_list(
            "/rest/api/pet", limit=limit, offset=offset,
            sort=sort, filters=filter, extra={"client_id": client_id},
        )

    @mcp.tool
    async def get_pet_by_id(
        pet_id: int,
    ) -> dict:
        """Get a pet by its unique ID.

        Args:
            pet_id: Unique numeric ID of the pet.
        """
        return await crud_get_by_id("/rest/api/pet", pet_id)

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
            alias: Pet's name/alias.
            client_id: ID of the owner (client).
            type_id: Animal type ID (species). Use 0 if unknown.
            breed_id: Breed ID. Use 0 if unknown.
            birthday: Date of birth in YYYY-MM-DD format (optional).
            note: Additional notes about the pet.
        """
        payload: dict = {"alias": alias, "client_id": client_id}
        if type_id:
            payload["type_id"] = type_id
        if breed_id:
            payload["breed_id"] = breed_id
        if birthday:
            payload["birthday"] = birthday
        if note:
            payload["note"] = note
        return await crud_create("/rest/api/pet", payload)

    @mcp.tool
    async def update_pet(
        pet_id: int,
        alias: str = "",
        owner_id: int = 0,
        type_id: int = 0,
        breed_id: int = 0,
        sex: str = "",
        birthday: str = "",
        note: str = "",
        color_id: int = 0,
        chip_number: str = "",
        weight: str = "",
        status: str = "",
    ) -> dict:
        """Update an existing pet's details.

        Args:
            pet_id: ID of the pet to update.
            alias: New pet name/alias (leave empty to keep current).
            owner_id: New owner (client) ID (0 = no change).
            type_id: New animal type ID (0 = no change).
            breed_id: New breed ID (0 = no change).
            sex: Pet sex: 'male', 'female', 'castrated', 'sterilized' (leave empty to keep current).
            birthday: Date of birth in YYYY-MM-DD format (leave empty to keep current).
            note: Updated notes about the pet.
            color_id: New color ID (0 = no change).
            chip_number: Microchip number (leave empty to keep current).
            weight: Pet weight as string, e.g. '5.2' (leave empty to keep current).
            status: New status (leave empty to keep current).
        """
        payload: dict = {}
        if alias:
            payload["alias"] = alias
        if owner_id:
            payload["owner_id"] = owner_id
        if type_id:
            payload["type_id"] = type_id
        if breed_id:
            payload["breed_id"] = breed_id
        if sex:
            payload["sex"] = sex
        if birthday:
            payload["birthday"] = birthday
        if note:
            payload["note"] = note
        if color_id:
            payload["color_id"] = color_id
        if chip_number:
            payload["chip_number"] = chip_number
        if weight:
            payload["weight"] = weight
        if status:
            payload["status"] = status
        return await crud_update("/rest/api/pet", pet_id, payload)

    @mcp.tool
    async def delete_pet(
        pet_id: int,
    ) -> dict:
        """Delete a pet by its ID.

        WARNING: This permanently removes the pet record. Use with caution.

        Args:
            pet_id: ID of the pet to delete.
        """
        return await crud_delete("/rest/api/pet", pet_id)

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
        import asyncio as _asyncio
        import json as _json

        vc = VetmanagerClient()

        mc_filter = _json.dumps(
            [{"property": "patient_id", "value": str(pet_id), "operator": "="}],
            separators=(",", ":"),
        )
        mc_sort = _json.dumps(
            [{"property": "id", "direction": "DESC"}],
            separators=(",", ":"),
        )

        pet_resp, mc_resp, vacc_resp = await _asyncio.gather(
            vc.get(f"/rest/api/pet/{pet_id}"),
            vc.get("/rest/api/MedicalCards", params={"filter": mc_filter, "sort": mc_sort, "limit": 5}),
            vc.get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": pet_id, "limit": 100}),
        )

        pet_data = pet_resp.get("data", {}).get("pet", {})
        mc_data = mc_resp.get("data", {})
        medical_cards = (
            mc_data.get("medicalCards")
            or mc_data.get("medicalcards")
            or []
        ) if isinstance(mc_data, dict) else []

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

    @mcp.tool
    async def get_inactive_pets(
        months: int = 6,
        limit: LimitParam = 50,
    ) -> dict:
        """Find pets that have not visited the clinic for N months.

        A "visit" is detected from three sources: admissions, invoices, and
        medical card records. If a pet has any of these after the cutoff date,
        it is considered active. Useful for reactivation campaigns.

        Args:
            months: Number of months without a visit to consider a pet inactive (default 6).
            limit: Max inactive pets to return (1–100, default 50).
        """
        import asyncio as _asyncio

        if months < 1:
            months = 1

        cutoff_date = (date.today() - timedelta(days=months * 30)).isoformat()

        (recent_admissions, _), (recent_invoices, _), (recent_medcards, _), (all_pets, total_pets) = (
            await _asyncio.gather(
                paginate_all(
                    "/rest/api/admission",
                    filters=[{"property": "admission_date", "value": cutoff_date, "operator": ">="}],
                    entity_key="admission",
                ),
                paginate_all(
                    "/rest/api/invoice",
                    filters=[{"property": "date", "value": cutoff_date, "operator": ">="}],
                    entity_key="invoice",
                ),
                paginate_all(
                    "/rest/api/MedicalCards",
                    filters=[{"property": "date_create", "value": cutoff_date, "operator": ">="}],
                    entity_key="medicalCards",
                ),
                paginate_all(
                    "/rest/api/pet",
                    entity_key="pet",
                ),
            )
        )

        active_pet_ids: set[int] = set()
        for adm in recent_admissions:
            pid = adm.get("patient_id")
            if pid:
                active_pet_ids.add(int(pid))
        for inv in recent_invoices:
            pid = inv.get("pet_id")
            if pid:
                active_pet_ids.add(int(pid))
        for mc in recent_medcards:
            pid = mc.get("patient_id")
            if pid:
                active_pet_ids.add(int(pid))

        inactive_pets = [
            pet for pet in all_pets
            if int(pet.get("id", 0)) not in active_pet_ids
        ]

        return {
            "inactive_pets": inactive_pets[:limit],
            "total_pets": total_pets,
            "total_inactive": len(inactive_pets),
            "cutoff_date": cutoff_date,
            "months": months,
        }

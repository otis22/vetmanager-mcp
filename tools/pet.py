from fastmcp import FastMCP

from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete
from validators import LimitParam
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_pets(
        limit: LimitParam = 20,
        offset: int = 0,
        owner_id: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List pets in the clinic, optionally filtered by owner.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            owner_id: Filter pets by owner's client ID (0 = no filter).
                Note: Vetmanager pet table uses `owner_id` as the foreign key
                to client.id (not client_id).
            sort: Optional sort spec (forwarded to API).
            filter: Optional filter spec (forwarded to API).
        """
        combined_filters: list[dict] = list(filter or [])
        if owner_id:
            combined_filters.append(
                {"property": "owner_id", "value": owner_id, "operator": "="}
            )
        return await crud_list(
            "/rest/api/pet",
            limit=limit,
            offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
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
        months_min: int = 13,
        months_max: int = 24,
        limit: LimitParam = 50,
    ) -> dict:
        """Find pets whose owners have not visited the clinic recently.

        Identifies "lapsed" pets via the owner's `client.last_visit_date`.
        Default window is 13–24 months ago. For each lapsed client, checks
        invoices first and medical cards as fallback to identify which specific
        pets were at the last visit (a client may have multiple pets, but only
        some were brought).

        Returns the top N pets sorted by their owner's last_visit_date DESC
        (most recently lapsed first). Default limit is 50 to prevent
        accidentally fetching the whole base.

        Args:
            months_min: Minimum age of owner's last visit in months (default 13).
            months_max: Maximum age of owner's last visit in months (default 24).
            limit: Max pets to return (1–100, default 50).
        """
        from tools._inactive_helpers import (
            fetch_inactive_clients_page,
            find_pets_at_client_last_visit,
        )

        # Pagination loop: scan inactive clients page-by-page until we either
        # accumulate `limit` pets or exhaust the inactive-client window.
        # This avoids the heuristic underfill where many clients have no
        # confirmed pets.
        CLIENT_PAGE_SIZE = 100
        MAX_CLIENT_PAGES = 20  # safety cap: 20 * 100 = 2000 clients scanned
        SAFETY_CAP_REACHED = False

        vc = VetmanagerClient()
        result_pets: list[dict] = []
        clients_scanned = 0
        cutoff_oldest = ""
        cutoff_newest = ""
        offset = 0

        for page_num in range(MAX_CLIENT_PAGES):
            clients, cutoff_oldest, cutoff_newest = await fetch_inactive_clients_page(
                months_min=months_min,
                months_max=months_max,
                limit=CLIENT_PAGE_SIZE,
                offset=offset,
            )
            if not clients:
                break

            for client in clients:
                clients_scanned += 1
                client_id = client.get("id")
                last_visit = client.get("last_visit_date", "")
                if client_id is None or not last_visit:
                    continue

                visited_pets = await find_pets_at_client_last_visit(
                    vc, client_id=int(client_id), last_visit_date=last_visit
                )

                client_name_parts = [
                    client.get("last_name", ""),
                    client.get("first_name", ""),
                    client.get("middle_name", ""),
                ]
                client_name = " ".join(p for p in client_name_parts if p).strip()

                for pet in visited_pets:
                    result_pets.append({
                        "id": pet.get("id"),
                        "alias": pet.get("alias", ""),
                        "type_id": pet.get("type_id"),
                        "owner_id": pet.get("owner_id", client_id),
                        "owner_name": client_name,
                        "owner_phone": client.get("cell_phone", ""),
                        "last_visit_date": last_visit,
                        "visit_source": pet.get("visit_source"),
                    })
                    if len(result_pets) >= limit:
                        break

                if len(result_pets) >= limit:
                    break

            if len(result_pets) >= limit:
                break

            if len(clients) < CLIENT_PAGE_SIZE:
                # Last page reached; no more clients to scan
                break

            offset += CLIENT_PAGE_SIZE
            if page_num + 1 == MAX_CLIENT_PAGES:
                SAFETY_CAP_REACHED = True

        return {
            "inactive_pets": result_pets,
            "limit_applied": limit,
            "clients_scanned": clients_scanned,
            "cutoff_window": {"from": cutoff_oldest, "to": cutoff_newest},
            "months_min": months_min,
            "months_max": months_max,
            "safety_cap_reached": SAFETY_CAP_REACHED,
            "note": (
                "Returned top N pets confirmed at last client visit via invoice "
                "(or medcard fallback). Pass higher limit or different "
                "months_min/months_max to customize."
            ),
        }

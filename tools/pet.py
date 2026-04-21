from fastmcp import FastMCP

from filters import eq as _filter_eq, like as _filter_like
from resources.pet_profile import fetch as _fetch_pet_profile
from service_metrics import instrument_call as _instrument_call
from tools._inactive_helpers import (
    fetch_inactive_clients_page,
    find_pets_for_clients_last_visit,
)
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete
from validators import LimitParam
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_pets(
        limit: LimitParam = 20,
        offset: int = 0,
        owner_id: int = 0,
        alias: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List pets in the clinic, optionally filtered by owner and/or nickname.

        To find a specific pet by its nickname (кличка / alias): first resolve
        the owner via `get_clients(name=...)` to obtain the client id, then
        call `get_pets(owner_id=..., alias=...)`. Searching by alias alone is
        not supported — pet nicknames are not unique per clinic, so standalone
        alias search would return a mix of unrelated patients.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            owner_id: Filter pets by owner's client ID (0 = no filter).
                Note: Vetmanager pet table uses `owner_id` as the foreign key
                to client.id (not client_id).
            alias: Filter pets by nickname (partial LIKE match). MUST be
                combined with owner_id — standalone alias search is rejected
                to prevent wrong-patient results.
            sort: Optional sort spec (forwarded to API).
            filter: Optional filter spec (forwarded to API).
        """
        if alias and not owner_id:
            raise ValueError(
                "alias filter requires owner_id — pet nicknames are not "
                "unique per clinic. Resolve the owner first via "
                "get_clients(name=...), then pass owner_id and alias together."
            )

        combined_filters: list = list(filter or [])
        if owner_id:
            combined_filters.append(_filter_eq("owner_id", owner_id))
        if alias:
            combined_filters.append(_filter_like("alias", alias))
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
        owner_id: int,
        type_id: int = 0,
        breed_id: int = 0,
        birthday: str = "",
        note: str = "",
    ) -> dict:
        """Register a new pet for a client.

        Args:
            alias: Pet's name/alias.
            owner_id: ID of the owning client. The Vetmanager Pet table uses
                `owner_id` as the FK to client.id (not `client_id`); this name
                is consistent with get_pets/update_pet.
            type_id: Animal type ID (species). Use 0 if unknown.
            breed_id: Breed ID. Use 0 if unknown.
            birthday: Date of birth in YYYY-MM-DD format (optional).
            note: Additional notes about the pet.
        """
        payload: dict = {"alias": alias, "owner_id": owner_id}
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

        Stage 102.2: tool-level instrumentation wraps the aggregator.

        Args:
            pet_id: Unique numeric ID of the pet.
        """
        return await _instrument_call(
            "/rest/api/pet",
            "GET",
            lambda: _fetch_pet_profile(pet_id),
            operation="aggregate_profile",
            tool_name="get_pet_profile",
        )

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

            client_pet_pairs = await find_pets_for_clients_last_visit(
                vc,
                clients=clients,
                limit=limit - len(result_pets),
            )

            for client, visited_pets in client_pet_pairs:
                clients_scanned += 1
                client_id = client.get("id")
                last_visit = client.get("last_visit_date", "")
                if client_id is None or not last_visit:
                    continue

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

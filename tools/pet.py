from fastmcp import FastMCP

from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_pets(
        domain: str,
        api_key: str,
        limit: int = 20,
        offset: int = 0,
        client_id: int = 0,
    ) -> dict:
        """List pets in the clinic, optionally filtered by owner.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            client_id: Filter pets by owner's client ID (0 = no filter).
        """
        validate_list_params(limit, offset)
        vc = VetmanagerClient(domain, api_key)
        params: dict = {"limit": limit, "offset": offset}
        if client_id:
            params["client_id"] = client_id
        return await vc.get("/rest/api/pet", params=params)

    @mcp.tool
    async def get_pet_by_id(
        domain: str,
        api_key: str,
        pet_id: int,
    ) -> dict:
        """Get a pet by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_id: Unique numeric ID of the pet.
        """
        vc = VetmanagerClient(domain, api_key)
        return await vc.get(f"/rest/api/pet/{pet_id}")

    @mcp.tool
    async def create_pet(
        domain: str,
        api_key: str,
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
        vc = VetmanagerClient(domain, api_key)
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
        domain: str,
        api_key: str,
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
        vc = VetmanagerClient(domain, api_key)
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

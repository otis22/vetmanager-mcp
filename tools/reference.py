"""Reference/lookup entity tools: Breed, PetType, City, CityType, Street, Unit,
Role, UserPosition, ComboManualName, ComboManualItem."""

from fastmcp import FastMCP
from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_breeds(limit: int = 20, offset: int = 0, pet_type_id: int = 0) -> dict:
        """List animal breeds in the clinic catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            pet_type_id: Filter by animal type ID (0 = no filter).
        """
        vc = VetmanagerClient()
        validate_list_params(limit, offset)
        params: dict = {"limit": limit, "offset": offset}
        if pet_type_id:
            params["petTypeId"] = pet_type_id
        return await vc.get("/rest/api/breed", params=params)

    @mcp.tool
    async def get_breed_by_id(breed_id: int) -> dict:
        """Get an animal breed by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            breed_id: Unique numeric ID of the breed.
        """
        return await VetmanagerClient().get(f"/rest/api/breed/{breed_id}")

    @mcp.tool
    async def get_pet_types(limit: int = 20, offset: int = 0) -> dict:
        """List animal types (species) available in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/petType", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_pet_type_by_id(pet_type_id: int) -> dict:
        """Get an animal type (species) by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_type_id: Unique numeric ID of the animal type.
        """
        return await VetmanagerClient().get(f"/rest/api/petType/{pet_type_id}")

    @mcp.tool
    async def get_cities(limit: int = 20, offset: int = 0, title: str = "") -> dict:
        """List cities in the system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            title: Filter by city name (partial match, optional).
        """
        vc = VetmanagerClient()
        validate_list_params(limit, offset)
        params: dict = {"limit": limit, "offset": offset}
        if title:
            params["title"] = title
        return await vc.get("/rest/api/city", params=params)

    @mcp.tool
    async def get_city_by_id(city_id: int) -> dict:
        """Get a city by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            city_id: Unique numeric ID of the city.
        """
        return await VetmanagerClient().get(f"/rest/api/city/{city_id}")

    @mcp.tool
    async def get_city_types(limit: int = 20, offset: int = 0) -> dict:
        """List city/settlement types (e.g. город, посёлок).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/cityType", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_streets(limit: int = 20, offset: int = 0, city_id: int = 0) -> dict:
        """List streets, optionally filtered by city.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            city_id: Filter by city ID (0 = no filter).
        """
        vc = VetmanagerClient()
        validate_list_params(limit, offset)
        params: dict = {"limit": limit, "offset": offset}
        if city_id:
            params["cityId"] = city_id
        return await vc.get("/rest/api/street", params=params)

    @mcp.tool
    async def get_street_by_id(street_id: int) -> dict:
        """Get a street by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            street_id: Unique numeric ID of the street.
        """
        return await VetmanagerClient().get(f"/rest/api/street/{street_id}")

    @mcp.tool
    async def get_units(limit: int = 20, offset: int = 0) -> dict:
        """List units of measurement used in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/unit", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_unit_by_id(unit_id: int) -> dict:
        """Get a unit of measurement by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            unit_id: Unique numeric ID of the unit.
        """
        return await VetmanagerClient().get(f"/rest/api/unit/{unit_id}")

    @mcp.tool
    async def get_roles(limit: int = 20, offset: int = 0) -> dict:
        """List user roles defined in the clinic system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/role", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_role_by_id(role_id: int) -> dict:
        """Get a user role by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            role_id: Unique numeric ID of the role.
        """
        return await VetmanagerClient().get(f"/rest/api/role/{role_id}")

    @mcp.tool
    async def get_user_positions(limit: int = 20, offset: int = 0) -> dict:
        """List staff positions (job titles) in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/userPosition", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_user_position_by_id(position_id: int) -> dict:
        """Get a staff position by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            position_id: Unique numeric ID of the position.
        """
        return await VetmanagerClient().get(f"/rest/api/userPosition/{position_id}")

    @mcp.tool
    async def get_combo_manual_names(limit: int = 20, offset: int = 0) -> dict:
        """List custom dropdown (combo) catalog names defined in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient().get("/rest/api/ComboManualName", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_combo_manual_name_by_id(name_id: int) -> dict:
        """Get a combo manual catalog name by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            name_id: Unique numeric ID of the catalog name.
        """
        return await VetmanagerClient().get(f"/rest/api/ComboManualName/{name_id}")

    @mcp.tool
    async def get_combo_manual_items(combo_manual_name_id: int, limit: int = 20, offset: int = 0) -> dict:
        """List items of a specific custom dropdown catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            combo_manual_name_id: ID of the parent catalog (ComboManualName).
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        vc = VetmanagerClient()
        return await vc.get("/rest/api/ComboManualItem", params={"comboManualNameId": combo_manual_name_id, "limit": limit, "offset": offset})

    @mcp.tool
    async def get_combo_manual_item_by_id(item_id: int) -> dict:
        """Get a combo manual catalog item by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            item_id: Unique numeric ID of the catalog item.
        """
        return await VetmanagerClient().get(f"/rest/api/ComboManualItem/{item_id}")

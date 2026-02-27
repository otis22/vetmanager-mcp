"""Reference/lookup entity tools: Breed, PetType, City, CityType, Street, Unit,
Role, UserPosition, ComboManualName, ComboManualItem."""

from fastmcp import FastMCP
from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_breeds(domain: str, api_key: str, limit: int = 20, offset: int = 0, pet_type_id: int = 0) -> dict:
        """List animal breeds in the clinic catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            pet_type_id: Filter by animal type ID (0 = no filter).
        """
        vc = VetmanagerClient(domain, api_key)
        validate_list_params(limit, offset)
        params: dict = {"limit": limit, "offset": offset}
        if pet_type_id:
            params["petTypeId"] = pet_type_id
        return await vc.get("/rest/api/breed", params=params)

    @mcp.tool
    async def get_breed_by_id(domain: str, api_key: str, breed_id: int) -> dict:
        """Get an animal breed by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            breed_id: Unique numeric ID of the breed.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/breed/{breed_id}")

    @mcp.tool
    async def get_pet_types(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List animal types (species) available in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/petType", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_pet_type_by_id(domain: str, api_key: str, pet_type_id: int) -> dict:
        """Get an animal type (species) by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            pet_type_id: Unique numeric ID of the animal type.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/petType/{pet_type_id}")

    @mcp.tool
    async def get_cities(domain: str, api_key: str, limit: int = 20, offset: int = 0, title: str = "") -> dict:
        """List cities in the system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            title: Filter by city name (partial match, optional).
        """
        vc = VetmanagerClient(domain, api_key)
        validate_list_params(limit, offset)
        params: dict = {"limit": limit, "offset": offset}
        if title:
            params["title"] = title
        return await vc.get("/rest/api/city", params=params)

    @mcp.tool
    async def get_city_by_id(domain: str, api_key: str, city_id: int) -> dict:
        """Get a city by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            city_id: Unique numeric ID of the city.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/city/{city_id}")

    @mcp.tool
    async def get_city_types(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List city/settlement types (e.g. город, посёлок).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/cityType", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_streets(domain: str, api_key: str, limit: int = 20, offset: int = 0, city_id: int = 0) -> dict:
        """List streets, optionally filtered by city.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
            city_id: Filter by city ID (0 = no filter).
        """
        vc = VetmanagerClient(domain, api_key)
        validate_list_params(limit, offset)
        params: dict = {"limit": limit, "offset": offset}
        if city_id:
            params["cityId"] = city_id
        return await vc.get("/rest/api/street", params=params)

    @mcp.tool
    async def get_street_by_id(domain: str, api_key: str, street_id: int) -> dict:
        """Get a street by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            street_id: Unique numeric ID of the street.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/street/{street_id}")

    @mcp.tool
    async def get_units(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List units of measurement used in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/unit", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_unit_by_id(domain: str, api_key: str, unit_id: int) -> dict:
        """Get a unit of measurement by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            unit_id: Unique numeric ID of the unit.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/unit/{unit_id}")

    @mcp.tool
    async def get_roles(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List user roles defined in the clinic system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/role", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_role_by_id(domain: str, api_key: str, role_id: int) -> dict:
        """Get a user role by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            role_id: Unique numeric ID of the role.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/role/{role_id}")

    @mcp.tool
    async def get_user_positions(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List staff positions (job titles) in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/userPosition", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_user_position_by_id(domain: str, api_key: str, position_id: int) -> dict:
        """Get a staff position by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            position_id: Unique numeric ID of the position.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/userPosition/{position_id}")

    @mcp.tool
    async def get_combo_manual_names(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List custom dropdown (combo) catalog names defined in the clinic.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/ComboManualName", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_combo_manual_name_by_id(domain: str, api_key: str, name_id: int) -> dict:
        """Get a combo manual catalog name by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            name_id: Unique numeric ID of the catalog name.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/ComboManualName/{name_id}")

    @mcp.tool
    async def get_combo_manual_items(domain: str, api_key: str, combo_manual_name_id: int, limit: int = 20, offset: int = 0) -> dict:
        """List items of a specific custom dropdown catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            combo_manual_name_id: ID of the parent catalog (ComboManualName).
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        vc = VetmanagerClient(domain, api_key)
        return await vc.get("/rest/api/ComboManualItem", params={"comboManualNameId": combo_manual_name_id, "limit": limit, "offset": offset})

    @mcp.tool
    async def get_combo_manual_item_by_id(domain: str, api_key: str, item_id: int) -> dict:
        """Get a combo manual catalog item by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            item_id: Unique numeric ID of the catalog item.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/ComboManualItem/{item_id}")

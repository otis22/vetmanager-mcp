"""Reference/lookup entity tools: Breed, PetType, City, CityType, Street, Unit,
Role, UserPosition, ComboManualName, ComboManualItem."""

from fastmcp import FastMCP
from filters import eq as _filter_eq, like as _filter_like
from tools.crud_helpers import crud_list, crud_get_by_id
from validators import LimitParam


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_breeds(
        limit: LimitParam = 20,
        offset: int = 0,
        pet_type_id: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List animal breeds in the clinic catalog.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            pet_type_id: Filter by animal type ID (0 = no filter).
        """
        combined_filters: list = list(filter or [])
        if pet_type_id:
            combined_filters.append(_filter_eq("pet_type_id", pet_type_id))
        return await crud_list(
            "/rest/api/breed", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_breed_by_id(breed_id: int) -> dict:
        """Get an animal breed by its unique ID.

        Args:
            breed_id: Unique numeric ID of the breed.
        """
        return await crud_get_by_id("/rest/api/breed", breed_id)

    @mcp.tool
    async def get_pet_types(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List animal types (species) available in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/petType", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_pet_type_by_id(pet_type_id: int) -> dict:
        """Get an animal type (species) by its unique ID.

        Args:
            pet_type_id: Unique numeric ID of the animal type.
        """
        return await crud_get_by_id("/rest/api/petType", pet_type_id)

    @mcp.tool
    async def get_cities(
        limit: LimitParam = 20,
        offset: int = 0,
        title: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List cities in the system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            title: Filter by city name (partial match, optional).
        """
        combined_filters: list = list(filter or [])
        if title:
            combined_filters.append(_filter_like("title", f"%{title}%"))
        return await crud_list(
            "/rest/api/city", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_city_by_id(city_id: int) -> dict:
        """Get a city by its unique ID.

        Args:
            city_id: Unique numeric ID of the city.
        """
        return await crud_get_by_id("/rest/api/city", city_id)

    @mcp.tool
    async def get_city_types(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List city/settlement types (e.g. город, посёлок).

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/cityType", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_streets(
        limit: LimitParam = 20,
        offset: int = 0,
        city_id: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List streets, optionally filtered by city.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            city_id: Filter by city ID (0 = no filter).
        """
        combined_filters: list = list(filter or [])
        if city_id:
            combined_filters.append(_filter_eq("city_id", city_id))
        return await crud_list(
            "/rest/api/street", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_street_by_id(street_id: int) -> dict:
        """Get a street by its unique ID.

        Args:
            street_id: Unique numeric ID of the street.
        """
        return await crud_get_by_id("/rest/api/street", street_id)

    @mcp.tool
    async def get_units(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List units of measurement used in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/unit", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_unit_by_id(unit_id: int) -> dict:
        """Get a unit of measurement by its unique ID.

        Args:
            unit_id: Unique numeric ID of the unit.
        """
        return await crud_get_by_id("/rest/api/unit", unit_id)

    @mcp.tool
    async def get_roles(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List user roles defined in the clinic system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/role", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_role_by_id(role_id: int) -> dict:
        """Get a user role by its unique ID.

        Args:
            role_id: Unique numeric ID of the role.
        """
        return await crud_get_by_id("/rest/api/role", role_id)

    @mcp.tool
    async def get_user_positions(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List staff positions (job titles) in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/userPosition", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_user_position_by_id(position_id: int) -> dict:
        """Get a staff position by its unique ID.

        Args:
            position_id: Unique numeric ID of the position.
        """
        return await crud_get_by_id("/rest/api/userPosition", position_id)

    @mcp.tool
    async def get_combo_manual_names(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List custom dropdown (combo) catalog names defined in the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/ComboManualName", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def get_combo_manual_name_by_id(name_id: int) -> dict:
        """Get a combo manual catalog name by its unique ID.

        Args:
            name_id: Unique numeric ID of the catalog name.
        """
        return await crud_get_by_id("/rest/api/ComboManualName", name_id)

    @mcp.tool
    async def get_combo_manual_items(
        combo_manual_name_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List items of a specific custom dropdown catalog.

        Args:
            combo_manual_name_id: ID of the parent catalog (ComboManualName).
            limit: Max records to return.
            offset: Pagination offset.
        """
        combined_filters: list = list(filter or [])
        if combo_manual_name_id:
            combined_filters.append(
                _filter_eq("combo_manual_name_id", combo_manual_name_id)
            )
        return await crud_list(
            "/rest/api/ComboManualItem", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_combo_manual_item_by_id(item_id: int) -> dict:
        """Get a combo manual catalog item by its unique ID.

        Args:
            item_id: Unique numeric ID of the catalog item.
        """
        return await crud_get_by_id("/rest/api/ComboManualItem", item_id)

"""Warehouse/inventory entity tools: GoodGroup, GoodSaleParam, PartyAccount,
PartyAccountDoc, StoreDocument, Suppliers."""

from fastmcp import FastMCP
from validators import build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_good_groups(
        limit: int = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List product/service groups in the clinic catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/GoodGroup", params=params)

    @mcp.tool
    async def get_good_group_by_id(group_id: int) -> dict:
        """Get a product/service group by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            group_id: Unique numeric ID of the group.
        """
        return await VetmanagerClient().get(f"/rest/api/GoodGroup/{group_id}")

    @mcp.tool
    async def get_good_sale_params(
        good_id: int,
        limit: int = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List sale parameters (pricing, units) for a specific good/service.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            good_id: ID of the good/service.
            limit: Max records to return.
            offset: Pagination offset.
        """
        vc = VetmanagerClient()
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=filter,
            extra={"goodId": good_id},
        )
        return await vc.get("/rest/api/goodSaleParam", params=params)

    @mcp.tool
    async def get_good_sale_param_by_id(param_id: int) -> dict:
        """Get a good sale parameter record by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            param_id: Unique numeric ID of the sale parameter.
        """
        return await VetmanagerClient().get(f"/rest/api/goodSaleParam/{param_id}")

    @mcp.tool
    async def get_party_accounts(
        limit: int = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List inventory batch (party) accounts.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/PartyAccount", params=params)

    @mcp.tool
    async def get_party_account_by_id(party_id: int) -> dict:
        """Get an inventory batch account by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            party_id: Unique numeric ID of the party account.
        """
        return await VetmanagerClient().get(f"/rest/api/PartyAccount/{party_id}")

    @mcp.tool
    async def get_party_account_docs(
        limit: int = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List documents associated with inventory batch accounts.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/PartyAccountDoc", params=params)

    @mcp.tool
    async def get_party_account_doc_by_id(doc_id: int) -> dict:
        """Get a batch account document by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            doc_id: Unique numeric ID of the document.
        """
        return await VetmanagerClient().get(f"/rest/api/PartyAccountDoc/{doc_id}")

    @mcp.tool
    async def get_store_documents(
        limit: int = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List warehouse/store documents (receipts, write-offs, transfers).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/StoreDocument", params=params)

    @mcp.tool
    async def get_store_document_by_id(doc_id: int) -> dict:
        """Get a store document by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            doc_id: Unique numeric ID of the store document.
        """
        return await VetmanagerClient().get(f"/rest/api/StoreDocument/{doc_id}")

    @mcp.tool
    async def get_suppliers(
        limit: int = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List suppliers/counterparties in the clinic system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/Suppliers", params=params)

    @mcp.tool
    async def get_supplier_by_id(supplier_id: int) -> dict:
        """Get a supplier by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            supplier_id: Unique numeric ID of the supplier.
        """
        return await VetmanagerClient().get(f"/rest/api/Suppliers/{supplier_id}")

    @mcp.tool
    async def get_good_stock_balance(
        good_id: int,
        clinic_id: int = 1,
    ) -> dict:
        """Get the current stock balance (remaining quantity) for a specific good in the warehouse.

        Uses the dedicated RestOfGoodInWarehouse endpoint which returns the actual
        remaining quantity accounting for all receipts and write-offs.
        Both good_id and clinic_id are required by the API.

        Args:
            good_id: ID of the good/product to check stock for.
            clinic_id: Clinic/branch ID (default 1 — main clinic).
        """
        result = await VetmanagerClient().get(
            "/rest/api/stores/RestOfGoodInWarehouse/",
            params={"good_id": good_id, "clinic_id": clinic_id},
        )
        quantity_str = (
            result.get("data", {})
            .get("rest_good_in_warehouse", {})
            .get("quantity", "0")
        )
        return {
            "good_id": good_id,
            "clinic_id": clinic_id,
            "quantity": float(quantity_str),
            "quantity_str": quantity_str,
            "raw": result,
        }

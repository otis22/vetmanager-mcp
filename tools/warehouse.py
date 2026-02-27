"""Warehouse/inventory entity tools: GoodGroup, GoodSaleParam, PartyAccount,
PartyAccountDoc, StoreDocument, Suppliers."""

from fastmcp import FastMCP
from validators import validate_list_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_good_groups(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List product/service groups in the clinic catalog.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/GoodGroup", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_good_group_by_id(domain: str, api_key: str, group_id: int) -> dict:
        """Get a product/service group by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            group_id: Unique numeric ID of the group.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/GoodGroup/{group_id}")

    @mcp.tool
    async def get_good_sale_params(domain: str, api_key: str, good_id: int, limit: int = 20, offset: int = 0) -> dict:
        """List sale parameters (pricing, units) for a specific good/service.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            good_id: ID of the good/service.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        vc = VetmanagerClient(domain, api_key)
        return await vc.get("/rest/api/goodSaleParam", params={"goodId": good_id, "limit": limit, "offset": offset})

    @mcp.tool
    async def get_good_sale_param_by_id(domain: str, api_key: str, param_id: int) -> dict:
        """Get a good sale parameter record by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            param_id: Unique numeric ID of the sale parameter.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/goodSaleParam/{param_id}")

    @mcp.tool
    async def get_party_accounts(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List inventory batch (party) accounts.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/PartyAccount", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_party_account_by_id(domain: str, api_key: str, party_id: int) -> dict:
        """Get an inventory batch account by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            party_id: Unique numeric ID of the party account.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/PartyAccount/{party_id}")

    @mcp.tool
    async def get_party_account_docs(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List documents associated with inventory batch accounts.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/PartyAccountDoc", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_party_account_doc_by_id(domain: str, api_key: str, doc_id: int) -> dict:
        """Get a batch account document by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            doc_id: Unique numeric ID of the document.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/PartyAccountDoc/{doc_id}")

    @mcp.tool
    async def get_store_documents(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List warehouse/store documents (receipts, write-offs, transfers).

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/StoreDocument", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_store_document_by_id(domain: str, api_key: str, doc_id: int) -> dict:
        """Get a store document by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            doc_id: Unique numeric ID of the store document.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/StoreDocument/{doc_id}")

    @mcp.tool
    async def get_suppliers(domain: str, api_key: str, limit: int = 20, offset: int = 0) -> dict:
        """List suppliers/counterparties in the clinic system.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            limit: Max records to return.
            offset: Pagination offset.
        """
        validate_list_params(limit, offset)
        return await VetmanagerClient(domain, api_key).get("/rest/api/Suppliers", params={"limit": limit, "offset": offset})

    @mcp.tool
    async def get_supplier_by_id(domain: str, api_key: str, supplier_id: int) -> dict:
        """Get a supplier by its unique ID.

        Args:
            domain: Clinic subdomain.
            api_key: REST API key.
            supplier_id: Unique numeric ID of the supplier.
        """
        return await VetmanagerClient(domain, api_key).get(f"/rest/api/Suppliers/{supplier_id}")

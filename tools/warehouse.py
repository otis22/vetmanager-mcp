"""Warehouse/inventory entity tools: GoodGroup, GoodSaleParam, PartyAccount,
PartyAccountDoc, StoreDocument, Suppliers."""

from fastmcp import FastMCP
from validators import LimitParam, build_list_query_params
from vetmanager_client import VetmanagerClient


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_good_groups(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List product/service groups in the clinic catalog.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/GoodGroup", params=params)

    @mcp.tool
    async def get_good_group_by_id(group_id: int) -> dict:
        """Get a product/service group by its unique ID.

        Args:
            group_id: Unique numeric ID of the group.
        """
        return await VetmanagerClient().get(f"/rest/api/GoodGroup/{group_id}")

    @mcp.tool
    async def get_good_sale_params(
        good_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List sale parameters (pricing, units) for a specific good/service.

        Args:
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
            param_id: Unique numeric ID of the sale parameter.
        """
        return await VetmanagerClient().get(f"/rest/api/goodSaleParam/{param_id}")

    @mcp.tool
    async def get_party_accounts(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List inventory batch (party) accounts.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/PartyAccount", params=params)

    @mcp.tool
    async def get_party_account_by_id(party_id: int) -> dict:
        """Get an inventory batch account by its unique ID.

        Args:
            party_id: Unique numeric ID of the party account.
        """
        return await VetmanagerClient().get(f"/rest/api/PartyAccount/{party_id}")

    @mcp.tool
    async def get_party_account_docs(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List documents associated with inventory batch accounts.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/PartyAccountDoc", params=params)

    @mcp.tool
    async def get_party_account_doc_by_id(doc_id: int) -> dict:
        """Get a batch account document by its unique ID.

        Args:
            doc_id: Unique numeric ID of the document.
        """
        return await VetmanagerClient().get(f"/rest/api/PartyAccountDoc/{doc_id}")

    @mcp.tool
    async def get_store_documents(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List warehouse/store documents (receipts, write-offs, transfers).

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/StoreDocument", params=params)

    @mcp.tool
    async def get_store_document_by_id(doc_id: int) -> dict:
        """Get a store document by its unique ID.

        Args:
            doc_id: Unique numeric ID of the store document.
        """
        return await VetmanagerClient().get(f"/rest/api/StoreDocument/{doc_id}")

    @mcp.tool
    async def get_suppliers(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List suppliers/counterparties in the clinic system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        params = build_list_query_params(limit=limit, offset=offset, sort=sort, filters=filter)
        return await VetmanagerClient().get("/rest/api/Suppliers", params=params)

    @mcp.tool
    async def get_supplier_by_id(supplier_id: int) -> dict:
        """Get a supplier by its unique ID.

        Args:
            supplier_id: Unique numeric ID of the supplier.
        """
        return await VetmanagerClient().get(f"/rest/api/Suppliers/{supplier_id}")

    @mcp.tool
    async def create_supplier(
        company_name: str,
        contact_person: str = "",
        phone: str = "",
        mail: str = "",
        address: str = "",
        note: str = "",
    ) -> dict:
        """Create a new supplier/counterparty in the clinic system.

        Args:
            company_name: Company or individual name (required).
            contact_person: Contact person name.
            phone: Contact phone number.
            mail: Email address.
            address: Postal address.
            note: Additional notes.
        """
        vc = VetmanagerClient()
        payload: dict = {"company_name": company_name}
        if contact_person:
            payload["contact_person"] = contact_person
        if phone:
            payload["phone"] = phone
        if mail:
            payload["mail"] = mail
        if address:
            payload["address"] = address
        if note:
            payload["note"] = note
        return await vc.post("/rest/api/Suppliers", json=payload)

    @mcp.tool
    async def update_supplier(
        supplier_id: int,
        company_name: str = "",
        contact_person: str = "",
        phone: str = "",
        mail: str = "",
        address: str = "",
        note: str = "",
        status: str = "",
    ) -> dict:
        """Update an existing supplier/counterparty.

        Note: Vetmanager API does not allow deleting suppliers via REST.

        Args:
            supplier_id: ID of the supplier to update.
            company_name: Updated company name (leave empty to keep current).
            contact_person: Updated contact person name.
            phone: Updated phone number.
            mail: Updated email address.
            address: Updated postal address.
            note: Updated notes.
            status: Updated status.
        """
        vc = VetmanagerClient()
        payload: dict = {}
        if company_name:
            payload["company_name"] = company_name
        if contact_person:
            payload["contact_person"] = contact_person
        if phone:
            payload["phone"] = phone
        if mail:
            payload["mail"] = mail
        if address:
            payload["address"] = address
        if note:
            payload["note"] = note
        if status:
            payload["status"] = status
        return await vc.put(f"/rest/api/Suppliers/{supplier_id}", json=payload)

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

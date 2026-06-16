import json
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from filters import eq as _filter_eq, like as _filter_like
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update
from validators import LimitParam, validate_list_params
from exceptions import VetmanagerError
from vetmanager_client import VetmanagerClient


INVOICE_GOODS_PAGE_SIZE = 100
INVOICE_GOODS_MAX_PAGES = 5
INVOICE_GOODS_MAX_INSPECTED = 500
INVOICE_GOODS_MAX_TAG_IDS = 50
INVOICE_GOODS_MAX_OFFSET = 10_000


def _data_rows(payload: dict, key: str) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    rows = data.get(key)
    return rows if isinstance(rows, list) else []


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _negative_id_tag_id(value: Any) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return abs(number) if number < 0 else None


def _combination_tag_id(row: dict) -> int | None:
    return _positive_int(row.get("tag_id")) or _negative_id_tag_id(row.get("id"))


def _is_combination_row(row: dict) -> bool:
    if _combination_tag_id(row) is not None:
        return True
    return str(row.get("good_group") or "").strip() == "GoodsSets"


def _normalize_is_template(value: Any) -> bool | None:
    if value is True:
        return True
    if value is False:
        return False
    normalized = str(value).strip()
    if normalized == "1":
        return True
    if normalized == "0":
        return False
    return None


def _normalize_invoice_good_row(row: dict, *, tag: dict | None) -> dict:
    tag_id = _combination_tag_id(row)
    is_combination = tag_id is not None or _is_combination_row(row)
    normalized = dict(row)
    normalized["invoice_good_id"] = row.get("id")
    normalized["title"] = row.get("title") or row.get("name") or ""
    normalized["is_combination"] = is_combination
    normalized["combination_tag_id"] = tag_id
    normalized["is_template"] = (
        _normalize_is_template(tag.get("is_template")) if tag is not None else None
    ) if is_combination else False
    if tag is not None:
        normalized["combination"] = tag
    return normalized


async def _vm_get(path: str, *, params: dict[str, Any] | None = None) -> dict:
    try:
        return await VetmanagerClient().get(path, params=params)
    except VetmanagerError as exc:
        raise ToolError(str(exc)) from None


async def _fetch_good_tags(
    tag_ids: list[int],
    *,
    clinic_id: int,
    warnings: list[str],
) -> dict[int, dict]:
    if not tag_ids:
        return {}
    limited_ids = tag_ids[:INVOICE_GOODS_MAX_TAG_IDS]
    if len(tag_ids) > INVOICE_GOODS_MAX_TAG_IDS:
        warnings.append(
            f"goodTag enrichment capped at {INVOICE_GOODS_MAX_TAG_IDS} tag IDs; "
            "extra combination rows are treated as ambiguous."
        )
    filters = [{"property": "id", "value": limited_ids, "operator": "IN"}]
    try:
        payload = await _vm_get(
            "/rest/api/goodTag",
            params={
                "limit": len(limited_ids),
                "offset": 0,
                "clinic_id": clinic_id,
                "filter": json.dumps(filters, separators=(",", ":"), ensure_ascii=False),
            },
        )
    except ToolError as exc:
        warnings.append(f"goodTag enrichment failed: {exc}")
        return {}
    result: dict[int, dict] = {}
    for tag in _data_rows(payload, "goodTag"):
        tag_id = _positive_int(tag.get("id"))
        if tag_id is None:
            continue
        normalized = dict(tag)
        normalized["is_template"] = _normalize_is_template(tag.get("is_template"))
        result[tag_id] = normalized
    return result


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def search_invoice_goods(
        query: str = "",
        clinic_id: int = 1,
        limit: LimitParam = 20,
        offset: int = 0,
        category_id: int = 0,
        include_template_combinations: bool = False,
    ) -> dict:
        """Search invoice-ready goods, services, and ordinary combinations.

        Args:
            query: Text search mapped to Vetmanager search_query.
            clinic_id: Clinic ID for prices and availability context.
            limit: Max accepted rows to return (1-100).
            offset: Upstream offset for invoice-ready catalog pagination.
            category_id: Optional service/category ID.
            include_template_combinations: Include template combinations too.
                False by default so ordinary invoice combinations are shown
                while templates are filtered after goodTag enrichment.
        """
        validate_list_params(limit, offset)
        if clinic_id <= 0:
            raise ToolError("clinic_id must be a positive integer.")

        accepted: list[dict] = []
        warnings: list[str] = []
        inspected_count = 0
        upstream_pages_fetched = 0
        overfetch_cap_reached = False
        next_offset = offset
        requested_tag_ids: set[int] = set()
        tags: dict[int, dict] = {}
        tag_cap_warning_added = False

        while len(accepted) < limit and upstream_pages_fetched < INVOICE_GOODS_MAX_PAGES:
            if next_offset > INVOICE_GOODS_MAX_OFFSET:
                overfetch_cap_reached = True
                warnings.append(
                    f"invoice goods overfetch stopped before offset {next_offset}; "
                    f"maximum offset is {INVOICE_GOODS_MAX_OFFSET}."
                )
                break
            params: dict[str, Any] = {
                "clinic_id": clinic_id,
                "limit": INVOICE_GOODS_PAGE_SIZE,
                "offset": next_offset,
            }
            if query:
                params["search_query"] = query
            if category_id:
                params["category_id"] = category_id

            payload = await _vm_get("/rest/api/good/productsDataForInvoice", params=params)
            rows = _data_rows(payload, "good")
            upstream_pages_fetched += 1
            inspected_count += len(rows)
            if inspected_count >= INVOICE_GOODS_MAX_INSPECTED:
                overfetch_cap_reached = True

            tag_ids = sorted(
                {
                    tag_id
                    for row in rows
                    if _is_combination_row(row)
                    for tag_id in [_combination_tag_id(row)]
                    if tag_id is not None
                }
            )
            new_tag_ids = [tag_id for tag_id in tag_ids if tag_id not in requested_tag_ids]
            remaining_tag_budget = INVOICE_GOODS_MAX_TAG_IDS - len(requested_tag_ids)
            if new_tag_ids and remaining_tag_budget <= 0:
                if not tag_cap_warning_added:
                    warnings.append(
                        f"goodTag enrichment capped at {INVOICE_GOODS_MAX_TAG_IDS} tag IDs; "
                        "extra combination rows are treated as ambiguous."
                    )
                    tag_cap_warning_added = True
            elif new_tag_ids:
                tag_ids_to_fetch = new_tag_ids[:remaining_tag_budget]
                requested_tag_ids.update(tag_ids_to_fetch)
                if len(new_tag_ids) > remaining_tag_budget and not tag_cap_warning_added:
                    warnings.append(
                        f"goodTag enrichment capped at {INVOICE_GOODS_MAX_TAG_IDS} tag IDs; "
                        "extra combination rows are treated as ambiguous."
                    )
                    tag_cap_warning_added = True
                tags.update(
                    await _fetch_good_tags(
                        tag_ids_to_fetch,
                        clinic_id=clinic_id,
                        warnings=warnings,
                    )
                )

            for row in rows:
                if len(accepted) >= limit:
                    break
                if not _is_combination_row(row):
                    accepted.append(_normalize_invoice_good_row(row, tag=None))
                    continue

                tag_id = _combination_tag_id(row)
                tag = tags.get(tag_id) if tag_id is not None else None
                normalized = _normalize_invoice_good_row(row, tag=tag)
                if tag is None:
                    warnings.append(
                        f"missing goodTag metadata for combination tag_id={tag_id}; "
                        "default mode excludes ambiguous rows."
                    )
                    if include_template_combinations:
                        accepted.append(normalized)
                    continue
                if normalized["is_template"] is True and not include_template_combinations:
                    continue
                if normalized["is_template"] is None and not include_template_combinations:
                    warnings.append(
                        f"ambiguous template status for combination tag_id={tag_id}; "
                        "default mode excludes ambiguous rows."
                    )
                    continue
                accepted.append(normalized)

            if (
                len(accepted) >= limit
                or not rows
                or len(rows) < INVOICE_GOODS_PAGE_SIZE
                or inspected_count >= INVOICE_GOODS_MAX_INSPECTED
            ):
                break
            next_offset += INVOICE_GOODS_PAGE_SIZE

        if upstream_pages_fetched >= INVOICE_GOODS_MAX_PAGES and len(accepted) < limit:
            overfetch_cap_reached = True

        return {
            "success": True,
            "message": "",
            "data": {
                "items": accepted,
                "metadata": {
                    "requested_limit": limit,
                    "accepted_count": len(accepted),
                    "inspected_count": inspected_count,
                    "upstream_pages_fetched": upstream_pages_fetched,
                    "overfetch_cap_reached": overfetch_cap_reached,
                    "warnings": warnings,
                },
            },
        }

    @mcp.tool
    async def get_good_combination(tag_id: int, clinic_id: int = 1) -> dict:
        """Get one good/service combination with positions from goodTag.

        Args:
            tag_id: Positive combination tag ID.
            clinic_id: Clinic ID used to filter sale parameters in positions.
        """
        if tag_id <= 0:
            raise ToolError("tag_id must be a positive integer.")
        if clinic_id <= 0:
            raise ToolError("clinic_id must be a positive integer.")
        filters = [{"property": "id", "value": tag_id, "operator": "="}]
        payload = await _vm_get(
            "/rest/api/goodTag",
            params={
                "limit": 1,
                "offset": 0,
                "clinic_id": clinic_id,
                "filter": json.dumps(filters, separators=(",", ":"), ensure_ascii=False),
            },
        )
        rows = _data_rows(payload, "goodTag")
        if not rows:
            raise ToolError(f"good combination tag_id={tag_id} not found.")
        combination = dict(rows[0])
        combination["is_template"] = _normalize_is_template(combination.get("is_template"))
        return {"success": True, "message": "", "data": {"combination": combination}}

    @mcp.tool
    async def calculate_good_combination_price(
        tag_id: int,
        quantity: float = 1,
        clinic_id: int = 1,
    ) -> dict:
        """Calculate combination price through Vetmanager server logic.

        Args:
            tag_id: Positive combination tag ID.
            quantity: Quantity to calculate.
            clinic_id: Clinic ID for store, price, and availability context.
        """
        if tag_id <= 0:
            raise ToolError("tag_id must be a positive integer.")
        if quantity <= 0:
            raise ToolError("quantity must be greater than 0.")
        if clinic_id <= 0:
            raise ToolError("clinic_id must be a positive integer.")
        return await _vm_get(
            "/rest/api/good/checkProductData",
            params={
                "good_id": f"-{tag_id}",
                "tag_id": tag_id,
                "qty": float(quantity),
                "clinic_id": clinic_id,
            },
        )

    @mcp.tool
    async def get_goods(
        limit: LimitParam = 20,
        offset: int = 0,
        name: str = "",
        title: str = "",
        group_id: int = 0,
        is_active: bool | None = None,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List goods (products/services) in the clinic catalog.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            name: [DEPRECATED — use title=] Legacy server-side name query
                param. Kept for backward compatibility; will be removed.
            title: Filter by good title (LIKE match on the `title` field).
                Prefer this over `name` — it uses the standard filter API.
            group_id: Filter by product group ID.
            is_active: Filter by active status. None = no filter (default),
                True = only active, False = only inactive.
            sort: Optional sort spec.
            filter: Optional extra filter spec.
        """
        combined_filters: list = list(filter or [])
        if title:
            combined_filters.append(_filter_like("title", title))
        if group_id:
            combined_filters.append(_filter_eq("group_id", group_id))
        if is_active is not None:
            combined_filters.append(_filter_eq("is_active", 1 if is_active else 0))
        return await crud_list(
            "/rest/api/good", limit=limit, offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
            extra={"name": name},
        )

    @mcp.tool
    async def get_good_by_id(
        good_id: int,
    ) -> dict:
        """Get a good (product or service) by its unique ID.

        Args:
            good_id: Unique numeric ID of the good.
        """
        return await crud_get_by_id("/rest/api/good", good_id)

    @mcp.tool
    async def create_good(
        title: str,
        group_id: int = 0,
        unit_storage_id: int = 0,
        is_active: int = 1,
        code: str = "",
        is_for_sale: int = 1,
        prime_cost: float = 0.0,
        description: str = "",
    ) -> dict:
        """Create a new good (product or service) in the clinic catalog.

        Args:
            title: Name of the good or service (required).
            group_id: Product group ID (0 = no group).
            unit_storage_id: Unit of measurement ID (0 = default).
            is_active: Active status: 1 = active (default), 0 = inactive.
            code: Internal product code (optional).
            is_for_sale: Available for sale: 1 = yes (default), 0 = no.
            prime_cost: Cost price (0 = not set).
            description: Product description (optional).
        """
        payload: dict = {"title": title, "is_active": is_active, "is_for_sale": is_for_sale}
        if group_id:
            payload["group_id"] = group_id
        if unit_storage_id:
            payload["unit_storage_id"] = unit_storage_id
        if code:
            payload["code"] = code
        if prime_cost:
            payload["prime_cost"] = prime_cost
        if description:
            payload["description"] = description
        return await crud_create("/rest/api/good", payload)

    @mcp.tool
    async def update_good(
        good_id: int,
        title: str = "",
        group_id: int = 0,
        unit_storage_id: int = 0,
        is_active: int = -1,
        code: str = "",
        is_for_sale: int = -1,
        prime_cost: float = 0.0,
        description: str = "",
    ) -> dict:
        """Update an existing good (product or service).

        Args:
            good_id: ID of the good to update.
            title: Updated name (leave empty to keep current).
            group_id: Updated product group ID (0 = no change).
            unit_storage_id: Updated unit ID (0 = no change).
            is_active: Updated active status: 1 = active, 0 = inactive, -1 = no change.
            code: Updated product code.
            is_for_sale: Updated sale status: 1 = yes, 0 = no, -1 = no change.
            prime_cost: Updated cost price (0 = no change).
            description: Updated description.
        """
        payload: dict = {}
        if title:
            payload["title"] = title
        if group_id:
            payload["group_id"] = group_id
        if unit_storage_id:
            payload["unit_storage_id"] = unit_storage_id
        if is_active != -1:
            payload["is_active"] = is_active
        if code:
            payload["code"] = code
        if is_for_sale != -1:
            payload["is_for_sale"] = is_for_sale
        if prime_cost:
            payload["prime_cost"] = prime_cost
        if description:
            payload["description"] = description
        return await crud_update("/rest/api/good", good_id, payload)

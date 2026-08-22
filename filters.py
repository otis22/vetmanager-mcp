"""Typed filter builders for Vetmanager REST API `filter` query parameter.

Problem solved: raw `json.dumps([{"property": X, "value": Y, "operator": "="}])`
is repeated 15+ times across `tools/*.py` with subtle differences in operator
casing, value coercion and IN-handling. This module centralizes construction
into one typed primitive, producing the canonical dict shape via `to_dict()`.

Callers can still pass raw dicts to `validators.build_list_query_params` —
Filter objects are additive, not a breaking replacement. Migration of
existing tool callers tracked in stage 93b.

Usage:
    from filters import eq, in_, like

    filters = [eq("status", "ACTIVE"), in_("id", [1, 2, 3]), like("alias", "Rex%")]
    params = build_list_query_params(limit=20, filters=filters)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from observability_logging import RUNTIME_LOGGER
from service_metrics import record_business_event


# Stage 235: public fields confirmed by the read-only devtr6 probe. Unprobed
# endpoints deliberately have no entry and retain their existing behaviour.
FILTER_FIELDS_BY_ENTITY: dict[str, frozenset[str]] = {
    "cassaclose": frozenset({
        "amount", "amount_cashless", "closed_user_id", "date", "id", "id_cassa", "status",
    }),
    "payment": frozenset({
        "amount", "cassa_id", "cassaclose_id", "create_date", "description", "id",
        "invoice_id", "parent_id", "payed_user", "payment_type", "status",
    }),
    "invoice": frozenset({
        "amount", "call", "client_id", "clinic_id", "create_date", "creator_id",
        "description", "discount", "doctor_id", "fiscal_section_id", "id", "increase",
        "invoice_date", "night", "old_id", "paid_amount", "payment_status", "percent",
        "pet_id", "status",
    }),
    "closingOfInvoices": frozenset({"client_id", "create_date", "id", "minus_amount", "minus_document_id", "minus_type_document", "plus_amount", "plus_document_id", "plus_type_document"}),
    "cassa": frozenset({"assigned_user_id", "cashless_to_cassa_id", "client_cass", "clinic_id", "has_unfinished_docs", "id", "inventarization_date", "is_blocked", "is_system", "main_cassa", "operating_cassa_id", "show_in_cashflow", "status", "summa_cash", "summa_cashless", "title", "type"}),
    "admission": frozenset({"admission_date", "admission_length", "client_id", "clinic_id", "confirmation", "create_date", "creator_id", "description", "direct_direction", "escorter_id", "id", "invoices_sum", "is_auto_create", "patient_id", "reception_write_channel", "status", "type_id", "user_id"}),
    "client": frozenset({"address", "apartment", "balance", "cell_phone", "city", "city_id", "date_register", "discount", "email", "first_name", "has_contract", "home_phone", "how_find", "id", "in_blacklist", "lab_number", "last_name", "last_visit_date", "middle_name", "note", "number_of_journal", "phone_prefix", "registration_index", "status", "street_id", "type_id", "unsubscribe", "vip", "work_phone", "zip"}),
    "hospital": frozenset({"admission_id", "client_id", "clinic_id", "description", "end_date", "hospital_block_id", "id", "invoice_id", "pet_id", "place", "start_date", "status", "user_id"}),
    "hospitalBlock": frozenset({"clinic_id", "id", "is_daily_payment", "is_hourly_payment", "places_count", "reserved_places_count", "status", "title"}),
    "pet": frozenset({"alias", "birthday", "breed_id", "chip_number", "color_id", "date_register", "deathdate", "deathnote", "edit_date", "id", "lab_number", "note", "old_id", "owner_id", "picture", "sex", "status", "type_id", "weight"}),
    "user": frozenset({"address", "cell_phone", "email", "first_name", "id", "is_active", "is_limited", "last_name", "middle_name", "nickname", "phone", "position_id", "role_id", "sip_number"}),
    "clinics": frozenset({"address", "city_id", "email", "end_time", "guest_client_id", "id", "internet_address", "logo_url", "phone", "start_time", "status", "telegram", "time_zone", "title", "whatsapp"}),
    "timesheet": frozenset({"action_id", "all_day", "begin_datetime", "clinic_id", "doctor_id", "end_datetime", "id", "night", "shedule_id", "shift", "title", "type"}),
    "properties": frozenset({"clinic_id", "id", "property_name", "property_title", "property_value"}),
    "breed": frozenset({"id", "pet_type_id", "title"}),
    "petType": frozenset({"id", "picture", "title", "type"}),
    "city": frozenset({"id", "title", "type_id"}),
    "cityType": frozenset({"id", "title"}),
    "street": frozenset({"city_id", "id", "title", "type"}),
    "unit": frozenset({"id", "status", "title"}),
    "role": frozenset({"id", "name", "super"}),
    "userPosition": frozenset({"admission_length", "id", "title"}),
    "goodSaleParam": frozenset({"barcode", "clinic_id", "coefficient", "good_id", "id", "is_partial_sale", "is_skip_marking", "markup", "max_price", "min_price", "price", "price_formation", "status", "unit_sale_id"}),
    "good": frozenset({"barcode", "category_id", "code", "create_date", "description", "for_combination", "group_id", "id", "is_active", "is_call", "is_for_sale", "is_marking", "is_recipe", "is_warehouse_account", "prime_cost", "title", "unit_storage_id"}),
}


class FilterPropertyValidationError(ValueError):
    """Expected local rejection of a filter field not probed for this tool."""


def filter_contract_validation_enabled() -> bool:
    """Return the runtime kill switch for stage-235 local rejection."""
    return os.environ.get("FILTER_CONTRACT_VALIDATION_ENABLED", "1").lower() not in {
        "0", "false", "no", "off",
    }


def validate_filter_properties(
    filters: Iterable[Any] | None, allowed_properties: frozenset[str]
) -> None:
    """Reject unknown raw filter names before an upstream list request."""
    if not filter_contract_validation_enabled():
        return
    for item in filters or ():
        property_name = item.property if isinstance(item, Filter) else (
            item.get("property") if isinstance(item, dict) else None
        )
        if isinstance(property_name, str) and property_name not in allowed_properties:
            record_business_event("filter_property_rejected")
            RUNTIME_LOGGER.warning(
                "Unknown filter property rejected locally",
                extra={
                    "event_name": "filter_property_rejected",
                    "filter_property": property_name,
                },
            )
            raise FilterPropertyValidationError(
                f"Unknown filter property '{property_name}'. Allowed properties: "
                f"{', '.join(sorted(allowed_properties))}."
            )


class FilterOp(str, Enum):
    """Supported operators for VM REST filter clauses.

    The VM backend accepts mixed case (`"IN"` / `"in"`) per stage 82/83
    probe; we emit uppercase canonical form everywhere.
    """

    EQ = "="
    NE = "!="
    LT = "<"
    LTE = "<="
    GT = ">"
    GTE = ">="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"


@dataclass(frozen=True)
class Filter:
    """One filter clause for VM REST API.

    Produces the canonical dict shape `{"property", "value", "operator"}`
    accepted by the `filter` query parameter.
    """

    property: str
    value: Any
    operator: FilterOp

    def to_dict(self) -> dict[str, Any]:
        return {
            "property": self.property,
            "value": self.value,
            "operator": self.operator.value,
        }


def eq(property: str, value: Any) -> Filter:
    """property == value."""
    return Filter(property=property, value=value, operator=FilterOp.EQ)


def ne(property: str, value: Any) -> Filter:
    """property != value."""
    return Filter(property=property, value=value, operator=FilterOp.NE)


def lt(property: str, value: Any) -> Filter:
    """property < value."""
    return Filter(property=property, value=value, operator=FilterOp.LT)


def lte(property: str, value: Any) -> Filter:
    """property <= value."""
    return Filter(property=property, value=value, operator=FilterOp.LTE)


def gt(property: str, value: Any) -> Filter:
    """property > value."""
    return Filter(property=property, value=value, operator=FilterOp.GT)


def gte(property: str, value: Any) -> Filter:
    """property >= value."""
    return Filter(property=property, value=value, operator=FilterOp.GTE)


def in_(property: str, values: list[Any]) -> Filter:
    """property IN (v1, v2, ...).

    Values list is preserved as-is — the VM API parses JSON array directly
    without further coercion. Callers should pre-stringify if the entity
    expects string-typed ids.

    Empty lists are rejected (stage 96.5): VM API semantics for `IN []` are
    undefined — some endpoints return 500, some treat as match-all. Callers
    must explicitly handle the no-matches short-circuit before building the
    filter.
    """
    if not isinstance(values, (list, tuple)):
        raise TypeError(
            f"in_ requires a list/tuple of values, got {type(values).__name__}"
        )
    if not values:
        raise ValueError(
            "in_ requires at least one value; VM API behavior on IN [] is undefined. "
            "Short-circuit the no-matches case in the caller."
        )
    return Filter(property=property, value=list(values), operator=FilterOp.IN)


def not_in(property: str, values: list[Any]) -> Filter:
    """property NOT IN (v1, v2, ...). Empty lists rejected (see in_)."""
    if not isinstance(values, (list, tuple)):
        raise TypeError(
            f"not_in requires a list/tuple of values, got {type(values).__name__}"
        )
    if not values:
        raise ValueError(
            "not_in requires at least one value; VM API behavior on NOT IN [] is undefined."
        )
    return Filter(property=property, value=list(values), operator=FilterOp.NOT_IN)


def like(property: str, pattern: str) -> Filter:
    """property LIKE pattern (SQL % wildcards)."""
    return Filter(property=property, value=pattern, operator=FilterOp.LIKE)


def as_dict_list(filters: list[Filter] | list[dict] | None) -> list[dict] | None:
    """Normalize a mixed list of Filter objects and/or raw dicts to dicts.

    Passes raw dicts through unchanged to support gradual caller migration.
    Returns None for empty/None input so callers can omit the filter param.
    """
    if not filters:
        return None
    result: list[dict] = []
    for item in filters:
        if isinstance(item, Filter):
            result.append(item.to_dict())
        elif isinstance(item, dict):
            result.append(item)
        else:
            raise TypeError(
                f"filter items must be Filter or dict, got {type(item).__name__}"
            )
    return result


def build_list_query_params(
    limit: int,
    offset: int,
    sort: list[dict[str, Any]] | None = None,
    filters: list[dict[str, Any]] | list[Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build common list-query params with optional sort/filter blocks.

    `filters` may be a list of raw dicts (legacy callers) OR a list of
    `Filter` objects (typed builder). Mixed lists are also accepted.

    Stage 103.8: moved from `validators.py` — sits next to the filter
    primitives it serializes, eliminates the previous lazy import back to
    `filters.as_dict_list`.
    """
    # Lazy import avoids pulling pydantic at filter-module import time.
    from validators import validate_list_params

    validate_list_params(limit, offset)
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if sort:
        params["sort"] = json.dumps(sort, separators=(",", ":"), ensure_ascii=False)
    if filters:
        normalized = as_dict_list(filters)
        if normalized:
            params["filter"] = json.dumps(
                normalized, separators=(",", ":"), ensure_ascii=False
            )

    if extra:
        for key, value in extra.items():
            # Stage 106.4 (F6 fix): skip only None and empty string.
            # Previously also dropped numeric zero, which silently converted
            # `extra={"client_id": 0}` into an UNFILTERED query (full-table
            # scan, privacy risk). Callers wanting to omit a default value
            # should filter at the call site explicitly.
            if value is None or value == "":
                continue
            params[key] = value

    return params

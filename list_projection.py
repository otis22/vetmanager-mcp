"""Local MCP response projections for selected list tools.

The VM REST list response has no supported `fields` option. This module only
reduces the already sanitized and canonicalized result sent to the caller.
"""

from __future__ import annotations

from exceptions import ToolInputError, reportable_error
from depersonalization import REDACTED_ADDRESS, REDACTED_EMAIL, REDACTED_PHONE


LIST_FIELDS: dict[str, frozenset[str]] = {
    "get_admissions": frozenset("""
        id admission_date description client_id pet_id doctor_id type_id
        admission_length status clinic_id direct_direction creator_id create_date
        escorter_id reception_write_channel is_auto_create invoices_sum
        confirmation wait_time
    """.split()),
    "get_invoices": frozenset("""
        id doctor_id client_id pet_id description percent amount status
        invoice_date old_id night increase discount call paid_amount
        create_date payment_status clinic_id creator_id fiscal_section_id
    """.split()),
    "get_clients": frozenset("""
        id address home_phone work_phone note type_id how_find balance
        email city_id date_register cell_phone zip registration_index vip
        last_name first_name middle_name status discount lab_number street_id
        apartment unsubscribed in_blacklist last_visit_date number_of_journal
        phone_prefix
    """.split()),
}

COMPACT_FIELDS: dict[str, tuple[str, ...]] = {
    "get_admissions": (
        "id", "admission_date", "client_id", "pet_id", "doctor_id", "status",
        "type_id", "clinic_id",
    ),
    "get_invoices": (
        "id", "invoice_date", "client_id", "pet_id", "doctor_id", "amount",
        "paid_amount", "payment_status", "status",
    ),
    "get_clients": ("id", "last_name", "first_name", "middle_name", "status"),
}

LIST_ENTITY = {
    "get_admissions": "admission",
    "get_invoices": "invoice",
    "get_clients": "client",
}

LIST_RELATIONS = {
    "get_admissions": frozenset({"client", "pet", "invoices"}),
    "get_invoices": frozenset({"client", "pet", "d", "doctor", "invoiceDocuments"}),
    "get_clients": frozenset({"city_data", "street_data", "pets"}),
}

_CLIENT_CONTACTS = {
    "phone": REDACTED_PHONE,
    "home_phone": REDACTED_PHONE, "work_phone": REDACTED_PHONE,
    "cell_phone": REDACTED_PHONE, "phone_prefix": REDACTED_PHONE,
    "email": REDACTED_EMAIL, "address": REDACTED_ADDRESS,
    "zip": REDACTED_ADDRESS, "apartment": REDACTED_ADDRESS,
    "city_id": REDACTED_ADDRESS, "street_id": REDACTED_ADDRESS,
    "city_data": REDACTED_ADDRESS, "street_data": REDACTED_ADDRESS,
}
_REDACTED_CONTACT_NOTE = "[redacted-contact-note]"

SAFE_DATA_METADATA = frozenset({"totalCount", "truncated", "has_more", "limit", "offset"})
SAFE_RESPONSE_KEYS = frozenset({"success", "data", "message", "limit", "offset", "has_more"})


def selected_fields(tool_name: str, fields: list[str] | None, compact: bool) -> tuple[str, ...] | None:
    """Validate before I/O; None means the legacy full response."""
    if fields is not None and compact:
        raise ToolInputError("fields and compact cannot be combined")
    if fields is not None:
        if not fields:
            raise ToolInputError("fields must contain at least one field")
        unknown = set(fields) - LIST_FIELDS[tool_name]
        if unknown:
            raise ToolInputError(
                "Unknown or nested fields: " + ", ".join(sorted(unknown))
                + ". Use canonical top-level scalar names."
            )
        return tuple(dict.fromkeys(fields))
    return COMPACT_FIELDS[tool_name] if compact else None


def selected_include(tool_name: str, include: list[str] | None) -> frozenset[str] | None:
    if include is None:
        return None
    if not isinstance(include, list) or any(not isinstance(item, str) for item in include):
        raise ToolInputError("include must be a list of relation names")
    if len(set(include)) != len(include):
        raise ToolInputError("include contains duplicate relation names")
    unknown = set(include) - LIST_RELATIONS[tool_name]
    if unknown:
        raise ToolInputError("Unknown include relations: " + ", ".join(sorted(unknown)))
    return frozenset(include)


def _mask_contacts(value: object, *, client_record: bool = False) -> object:
    """Mask client/owner records in the already sanitized MCP result."""
    if isinstance(value, list):
        return [_mask_contacts(item, client_record=client_record) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {"client", "owner"} and item is not None and not isinstance(item, dict):
            raise reportable_error("Contact masking expected a client object.")
        if client_record and key in _CLIENT_CONTACTS and item is not None:
            result[key] = _CLIENT_CONTACTS[key]
        elif client_record and key == "note" and item is not None:
            if not isinstance(item, str):
                raise reportable_error("Contact masking expected a text note.")
            result[key] = _REDACTED_CONTACT_NOTE
        else:
            result[key] = _mask_contacts(item, client_record=key in {"client", "owner"})
    return result


PET_CONTACT_TOOLS = frozenset({"get_pets", "get_inactive_pets", "find_pets_by_alias"})


def mask_pet_list_result(result: object, tool_name: str) -> object:
    """Apply the stage-399 client mask to pet lists after required cleaning."""
    if not isinstance(result, dict):
        raise reportable_error("Contact masking expected a list response.")
    if result.get("success") is False:
        return result
    container_key = "inactive_pets" if tool_name == "get_inactive_pets" else "data"
    container = result.get(container_key)
    if tool_name == "get_inactive_pets":
        rows = container
        entity = None
    else:
        entity = "pets" if tool_name == "find_pets_by_alias" else "pet"
        if isinstance(container, list) and tool_name == "get_pets":
            rows = container
            entity = None
        elif isinstance(container, dict):
            rows = container.get(entity)
        else:
            rows = None
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise reportable_error("Contact masking expected pet records.")
    masked = []
    for row in rows:
        projected = _mask_contacts(row)
        if tool_name == "get_inactive_pets" and projected.get("owner_phone") is not None:
            projected["owner_phone"] = REDACTED_PHONE
        masked.append(projected)
    if tool_name == "get_inactive_pets":
        return {**result, container_key: masked}
    if entity is None:
        return {**result, "data": masked}
    return {**result, "data": {**container, entity: masked}}


def project_list_result(
    result: object, tool_name: str, selection: tuple[str, ...] | None,
    *, include: frozenset[str] | None = None, mask_contacts: bool = False,
):
    """Keep the envelope and row-level identifier-conflict warning intact."""
    if selection is None and include is None and not mask_contacts:
        return result
    if not isinstance(result, dict):
        raise reportable_error("Projection expected a list response envelope.")
    if result.get("success") is False:
        return result
    if set(result) - SAFE_RESPONSE_KEYS:
        raise reportable_error("Projection found unknown response metadata.")
    if any(isinstance(result[key], (dict, list, tuple))
           for key in set(result) - {"data"}):
        raise reportable_error("Projection expected scalar response metadata.")
    data = result.get("data")
    entity = LIST_ENTITY[tool_name]
    if isinstance(data, list):
        rows = data
        container = None
    elif isinstance(data, dict) and isinstance(data.get(entity), list):
        rows = data[entity]
        container = data
        if set(container) - {entity} - SAFE_DATA_METADATA:
            raise reportable_error("Projection found unknown list metadata.")
        if any(isinstance(container[key], (dict, list, tuple))
               for key in set(container) - {entity}):
            raise reportable_error("Projection expected scalar list metadata.")
    else:
        raise reportable_error("Projection expected a supported list response shape.")

    projected = []
    relations = LIST_RELATIONS[tool_name]
    allowed_relations = (relations if selection is None else frozenset()) if include is None else include
    for row in rows:
        if not isinstance(row, dict):
            raise reportable_error("Projection expected a record object.")
        row = _mask_contacts(row, client_record=tool_name == "get_clients") if mask_contacts else row
        if include is not None or selection is None:
            if any(key not in relations and key != "_mcp_identifier_conflicts"
                   and isinstance(value, (dict, list, tuple))
                   for key, value in row.items()):
                raise reportable_error("Projection found an unrecognized nested field.")
        scalar_fields = {}
        scalar_names = (key for key in row if key not in relations) if selection is None else selection
        for key in scalar_names:
            if key not in row:
                continue
            value = row[key]
            if selection is not None and isinstance(value, (dict, list, tuple)):
                raise reportable_error("Projection expected a scalar field.")
            scalar_fields[key] = value
        for key in allowed_relations:
            if key in row:
                value = row[key]
                if value is not None and not isinstance(value, (dict, list)) and not (
                    mask_contacts and key in {"city_data", "street_data"}
                    and value == REDACTED_ADDRESS
                ):
                    raise reportable_error("Projection expected a relation object or list.")
                scalar_fields[key] = value
        if "_mcp_identifier_conflicts" in row:
            scalar_fields["_mcp_identifier_conflicts"] = row["_mcp_identifier_conflicts"]
        projected.append(scalar_fields)
    new_data = projected if container is None else {**container, entity: projected}
    return {**result, "data": new_data}

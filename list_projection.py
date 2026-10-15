"""Local MCP response projections for selected list tools.

The VM REST list response has no supported `fields` option. This module only
reduces the already sanitized and canonicalized result sent to the caller.
"""

from __future__ import annotations

from exceptions import ToolInputError, reportable_error


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


def project_list_result(result: object, tool_name: str, selection: tuple[str, ...] | None):
    """Keep the envelope and row-level identifier-conflict warning intact."""
    if selection is None:
        return result
    if not isinstance(result, dict):
        raise reportable_error("Projection expected a list response envelope.")
    if result.get("success") is False:
        return result
    data = result.get("data")
    entity = LIST_ENTITY[tool_name]
    if isinstance(data, list):
        rows = data
        container = None
    elif isinstance(data, dict) and isinstance(data.get(entity), list):
        rows = data[entity]
        container = data
    else:
        raise reportable_error("Projection expected a supported list response shape.")

    projected = []
    for row in rows:
        if not isinstance(row, dict):
            raise reportable_error("Projection expected a record object.")
        scalar_fields = {}
        for key in selection:
            if key not in row:
                continue
            value = row[key]
            if isinstance(value, (dict, list, tuple)):
                raise reportable_error("Projection expected a scalar field.")
            scalar_fields[key] = value
        if "_mcp_identifier_conflicts" in row:
            scalar_fields["_mcp_identifier_conflicts"] = row["_mcp_identifier_conflicts"]
        projected.append(scalar_fields)
    new_data = projected if container is None else {**container, entity: projected}
    return {**result, "data": new_data}

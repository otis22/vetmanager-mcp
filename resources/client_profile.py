"""Client profile aggregator (stage 103c).

Composes the client's full record with last 5 invoices, last 5 admissions,
and next scheduled admission into a single response. Owns entity-specific
VM field names (`client_id` filter, `admission_date` sort, active-status
enum IN-filter) and response unwrapping.

Partial-failure semantics come from `tools._aggregation.gather_sections`:
any section that raises a VetmanagerError falls back to an empty shape
and the caller sees `partial: True` plus `section_errors`.
"""

from __future__ import annotations

from filters import build_list_query_params, eq as _filter_eq, in_ as _filter_in
from resources._aggregation import gather_sections
from resources.admission_status import ACTIVE_ADMISSION_STATUSES
from vetmanager_client import VetmanagerClient


async def fetch(client_id: int) -> dict:
    """Build a comprehensive client profile.

    Aggregates:
    - Full client record (`/rest/api/client/{id}`).
    - Last 5 invoices (filter=client_id, sort id DESC).
    - Last 5 admissions (filter=client_id, sort admission_date DESC).
    - Next scheduled admission (filter=client_id + status IN active tuple,
      sort admission_date ASC, limit 1).
    """
    vc = VetmanagerClient()

    client_id_str = str(client_id)
    common_filters = [_filter_eq("client_id", client_id_str)]
    invoices_params = build_list_query_params(
        limit=5,
        offset=0,
        sort=[{"property": "id", "direction": "DESC"}],
        filters=common_filters,
    )
    recent_admissions_params = build_list_query_params(
        limit=5,
        offset=0,
        sort=[{"property": "admission_date", "direction": "DESC"}],
        filters=common_filters,
    )
    # Stage 96.2: `status="active"` was a phantom enum value — admission.status
    # has no such literal. Use IN-filter with the canonical active-status
    # tuple so next_admission returns real upcoming visits instead of None.
    next_admission_params = build_list_query_params(
        limit=1,
        offset=0,
        sort=[{"property": "admission_date", "direction": "ASC"}],
        filters=[
            _filter_eq("client_id", client_id_str),
            _filter_in("status", list(ACTIVE_ADMISSION_STATUSES)),
        ],
    )

    sections = [
        ("client", vc.get(f"/rest/api/client/{client_id}"),
         {"data": {"client": {}}}),
        ("invoices", vc.get("/rest/api/invoice", params=invoices_params),
         {"data": {"invoice": []}}),
        ("recent_admissions", vc.get("/rest/api/admission", params=recent_admissions_params),
         {"data": {"admission": []}}),
        ("next_admission", vc.get("/rest/api/admission", params=next_admission_params),
         {"data": {"admission": []}}),
    ]
    payloads, section_errors = await gather_sections(
        tool_name="get_client_profile",
        context={"client_id": client_id},
        sections=sections,
    )
    client_payload, invoices_payload, admissions_payload, next_payload = payloads

    client_data = client_payload.get("data", {}).get("client", {})
    invoices = invoices_payload.get("data", {}).get("invoice", [])
    admissions = admissions_payload.get("data", {}).get("admission", [])
    next_admissions = next_payload.get("data", {}).get("admission", [])
    next_admission = next_admissions[0] if next_admissions else None

    result: dict = {
        "client": client_data,
        "last_invoices": invoices,
        "last_admissions": admissions,
        "next_admission": next_admission,
    }
    if section_errors:
        result["partial"] = True
        result["section_errors"] = section_errors
    return result

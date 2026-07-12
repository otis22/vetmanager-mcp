"""Pet profile aggregator (stage 103c).

Composes the pet's full record with owner, last 5 medical card entries, recent
invoices with line items, and vaccination records into a single response. Owns
entity-specific field
mapping (`patient_id` filter for MedicalCards — NOT `pet_id`), response
key fallback (`medicalCards` vs `medicalcards` from different upstream
versions), and the `last_vaccination_date` / `next_vaccination_date`
derivation from the latest vaccination record.
"""

from __future__ import annotations

import asyncio

from filters import build_list_query_params, eq as _filter_eq
from resources._aggregation import gather_sections
from runtime_auth import get_current_runtime_credentials
from token_scopes import SCOPE_CLIENTS_READ, SCOPE_FINANCE_READ
from vetmanager_client import VetmanagerClient


_INVOICE_LOOKUP_LIMIT = 20
_INVOICE_RESULT_LIMIT = 5
_INVOICE_DOCUMENT_LIMIT = 50


def _section_error(error_type: str, message: str, *, retryable: bool = False) -> dict:
    return {
        "error_type": error_type,
        "retryable": retryable,
        "message": message,
    }


def _has_scope(scope: str) -> bool:
    credentials = get_current_runtime_credentials()
    return credentials is None or scope in credentials.scopes


def _extract_rows(payload: dict, key: str) -> tuple[list[dict], int | None]:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return [], None
    rows = data.get(key) or []
    if not isinstance(rows, list):
        rows = []
    total_raw = data.get("totalCount")
    try:
        total = int(total_raw) if total_raw is not None else None
    except (TypeError, ValueError):
        total = None
    return [row for row in rows if isinstance(row, dict)], total


def _sort_invoices(invoices: list[dict]) -> list[dict]:
    return sorted(
        invoices,
        key=lambda row: (str(row.get("invoice_date") or ""), int(row.get("id") or 0)),
        reverse=True,
    )


async def fetch(pet_id: int) -> dict:
    """Build a comprehensive pet profile.

    Aggregates:
    - Full pet record (`/rest/api/pet/{id}`).
    - Last 5 medical card entries (filter by `patient_id`, sort id DESC).
    - All vaccination records (`/rest/api/MedicalCards/Vaccinations`).

    Derives `last_vaccination_date` (date part of the latest vaccination)
    and `next_vaccination_date` (`date_nexttime` of that same record) as
    explicit top-level fields so LLMs don't need to scan the vaccinations
    list to answer "when is the next vaccination due".
    """
    vc = VetmanagerClient()
    medical_cards_params = build_list_query_params(
        limit=5,
        offset=0,
        sort=[{"property": "id", "direction": "DESC"}],
        filters=[_filter_eq("patient_id", str(pet_id))],
    )
    invoice_params = build_list_query_params(
        limit=_INVOICE_LOOKUP_LIMIT,
        offset=0,
        sort=[
            {"property": "invoice_date", "direction": "DESC"},
            {"property": "id", "direction": "DESC"},
        ],
        filters=[_filter_eq("pet_id", str(pet_id))],
    )
    include_invoices = _has_scope(SCOPE_FINANCE_READ)

    sections = [
        ("pet", vc.get(f"/rest/api/pet/{pet_id}"),
         {"data": {"pet": {}}}),
        ("medical_cards", vc.get(
            "/rest/api/MedicalCards",
            params=medical_cards_params,
        ), {"data": {"medicalCards": []}}),
        ("vaccinations", vc.get(
            "/rest/api/MedicalCards/Vaccinations",
            params={"pet_id": pet_id, "limit": 100},
        ), {"data": {"medicalcards": []}}),
    ]
    if include_invoices:
        sections.append(
            ("invoices", vc.get("/rest/api/invoice", params=invoice_params),
             {"data": {"invoice": []}})
        )
    payloads, section_errors = await gather_sections(
        tool_name="get_pet_profile",
        context={"pet_id": pet_id},
        sections=sections,
    )
    pet_payload = payloads[0]
    mc_payload = payloads[1]
    vacc_payload = payloads[2]
    invoices_payload = payloads[3] if include_invoices else {"data": {"invoice": []}}
    if not include_invoices:
        section_errors["invoices"] = _section_error(
            "missing_scope",
            f"Missing optional scope for invoice section: {SCOPE_FINANCE_READ}",
        )

    pet_data = pet_payload.get("data", {}).get("pet", {})
    owner: dict = {}
    if _has_scope(SCOPE_CLIENTS_READ):
        owner_id = pet_data.get("owner_id") if isinstance(pet_data, dict) else None
        if owner_id:
            owner_payloads, owner_errors = await gather_sections(
                tool_name="get_pet_profile",
                context={"pet_id": pet_id, "owner_id": owner_id},
                sections=[
                    ("owner", vc.get(f"/rest/api/client/{owner_id}"),
                     {"data": {"client": {}}}),
                ],
            )
            owner = owner_payloads[0].get("data", {}).get("client", {})
            section_errors.update(owner_errors)
        elif "pet" not in section_errors:
            section_errors["owner"] = _section_error(
                "missing_owner_id",
                "Pet record does not include owner_id.",
            )
    else:
        section_errors["owner"] = _section_error(
            "missing_scope",
            f"Missing optional scope for owner section: {SCOPE_CLIENTS_READ}",
        )

    mc_data = mc_payload.get("data", {})
    medical_cards = (
        mc_data.get("medicalCards")
        or mc_data.get("medicalcards")
        or []
    ) if isinstance(mc_data, dict) else []

    vaccinations_raw = vacc_payload.get("data", {}).get("medicalcards", [])
    vaccinations = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "date": r.get("date"),
            "date_nexttime": r.get("date_nexttime"),
            "vaccine_id": r.get("vaccine_id"),
            "medcard_id": r.get("medcard_id"),
        }
        for r in vaccinations_raw
    ]

    sorted_vacc = sorted(
        vaccinations,
        key=lambda r: r.get("date") or "",
        reverse=True,
    )
    last_vaccination_date: str | None = None
    next_vaccination_date: str | None = None
    if sorted_vacc:
        last_vacc = sorted_vacc[0]
        last_vaccination_date = (last_vacc.get("date") or "").split(" ")[0] or None
        next_raw = last_vacc.get("date_nexttime") or ""
        next_vaccination_date = next_raw.strip() or None

    invoices_raw, invoices_total = _extract_rows(invoices_payload, "invoice")
    invoices = _sort_invoices(invoices_raw)[:_INVOICE_RESULT_LIMIT]
    invoice_document_errors: dict[str, dict] = {}
    if invoices:
        doc_sections = []
        for invoice in invoices:
            invoice_id = invoice.get("id")
            if not invoice_id:
                continue
            params = build_list_query_params(
                limit=_INVOICE_DOCUMENT_LIMIT,
                offset=0,
                filters=[_filter_eq("document_id", str(invoice_id))],
            )
            doc_sections.append(
                (str(invoice_id), vc.get("/rest/api/invoiceDocument", params=params), {"data": {"invoiceDocument": []}})
            )
        if doc_sections:
            doc_results = await asyncio.gather(
                *(section[1] for section in doc_sections),
                return_exceptions=True,
            )
            docs_by_invoice_id: dict[str, tuple[list[dict], int | None]] = {}
            for (invoice_id, _, _), result in zip(doc_sections, doc_results):
                if isinstance(result, Exception):
                    invoice_document_errors[invoice_id] = _section_error(
                        "invoice_documents_error",
                        f"{type(result).__name__}: {result}",
                        retryable=True,
                    )
                    docs_by_invoice_id[invoice_id] = ([], None)
                else:
                    docs_by_invoice_id[invoice_id] = _extract_rows(result, "invoiceDocument")
            for invoice in invoices:
                invoice_id = str(invoice.get("id") or "")
                docs, total = docs_by_invoice_id.get(invoice_id, ([], None))
                invoice["invoice_documents"] = docs
                invoice["invoice_documents_total"] = total
                invoice["invoice_documents_truncated"] = (
                    total is not None and total > len(docs)
                )
                if invoice_id in invoice_document_errors:
                    invoice["invoice_documents_error"] = invoice_document_errors[invoice_id]
                if invoice["invoice_documents_truncated"]:
                    invoice_document_errors[invoice_id] = _section_error(
                        "truncated",
                        f"Invoice document list truncated at {_INVOICE_DOCUMENT_LIMIT} rows.",
                    )
    if invoice_document_errors:
        section_errors["invoice_documents"] = invoice_document_errors

    result: dict = {
        "pet": pet_data,
        "owner": owner,
        "last_medical_cards": medical_cards,
        "last_invoices": invoices,
        "last_invoices_total": invoices_total,
        "vaccinations": vaccinations,
        "last_vaccination_date": last_vaccination_date,
        "next_vaccination_date": next_vaccination_date,
    }
    if section_errors:
        result["partial"] = True
        result["section_errors"] = section_errors
    return result

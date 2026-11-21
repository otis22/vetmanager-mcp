"""Read-only source bundle for an agent-written patient discharge draft."""

from datetime import date
import json
import re

from exceptions import ToolInputError, reportable_error
from filters import build_list_query_params, eq
from runtime_auth import get_current_runtime_credentials
from token_scopes import SCOPE_FINANCE_READ
from vetmanager_client import VetmanagerClient

_PAGE_CAP = 100
_ROW_CAP = 10_000
_INVOICE_LINE_REQUEST_CAP = 100
_FIELDS = {
    "admissions": ("id", "patient_id", "admission_date", "type_id", "status", "description", "user_id", "clinic_id"),
    "medical_cards": ("id", "patient_id", "admission_id", "date_create", "date_edit", "doctor_id", "clinic_id", "description", "diagnos", "diagnos_text", "diagnos_type_text", "diagnoses", "treatment", "healing_process", "recomendation", "recommendation", "weight", "temperature", "admission_type", "meet_result_id", "next_meet_id", "status"),
    "hospitalizations": ("id", "pet_id", "start_date", "end_date", "description", "status", "user_id", "clinic_id", "admission_id"),
    "invoices": ("id", "pet_id", "invoice_date", "create_date", "description", "status"),
    "invoice_documents": ("id", "document_id", "good_id", "quantity", "good"),
    "vaccinations": ("id", "medcard_id", "date", "name", "vaccine_id", "doza_value", "date_nexttime", "next_admission_id"),
    "pet": ("id", "alias", "type_id", "type", "breed_id", "breed", "sex", "birthday", "chip_number", "lab_number"),
}
_ENDPOINTS = {
    "admissions": ("/rest/api/admission", "admission", "patient_id"),
    "medical_cards": ("/rest/api/MedicalCards", "medicalCards", "patient_id"),
    "hospitalizations": ("/rest/api/hospital", "hospital", "pet_id"),
    "invoices": ("/rest/api/invoice", "invoice", "pet_id"),
}


def _day(value: object) -> date | None:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _project(section: str, row: dict) -> dict:
    result = {field: row[field] for field in _FIELDS[section] if field in row}
    if section == "vaccinations" and "name" in result:
        result["vaccine_name"] = result.pop("name")
    if section == "medical_cards" and isinstance(result.get("diagnoses"), list):
        result["diagnoses"] = [
            {key: diagnosis[key] for key in ("id", "title", "status") if key in diagnosis}
            for diagnosis in result["diagnoses"] if isinstance(diagnosis, dict)
        ]
    if section == "invoice_documents" and isinstance(result.get("good"), dict):
        good = result["good"]
        result["good"] = {key: good[key] for key in ("id", "title", "description") if key in good}
    return result


def _diagnosis_title_unresolved(row: dict) -> bool:
    raw = row.get("diagnos")
    if raw in (None, "", "0", "[]", 0):
        return False
    try:
        references = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return True
    if not isinstance(references, list) or not references:
        return True
    diagnoses = row.get("diagnoses")
    resolved_ids = ({str(item.get("id")) for item in diagnoses
                     if isinstance(item, dict) and isinstance(item.get("title"), str)
                     and item["title"].strip()} if isinstance(diagnoses, list) else set())
    return any(not isinstance(reference, dict) or reference.get("id") is None
               or str(reference["id"]) not in resolved_ids for reference in references)


def _select_period(section: str, rows: list[dict], start: date, end: date,
                   admission_ids: set[int | str]) -> tuple[list[dict], list[str]]:
    selected, gaps = [], []
    linked_admission_ids = {str(identifier) for identifier in admission_ids}
    for row in rows:
        if section == "hospitalizations":
            first, last = _day(row.get("start_date")), _day(row.get("end_date"))
            # An unknown boundary leaves the interval unresolved. Preserve it.
            include = (first is None or first <= end) and (last is None or last >= start)
            uncertain = first is None or last is None
        else:
            field = {"admissions": "admission_date", "medical_cards": "date_create",
                     "vaccinations": "date", "invoices": "invoice_date"}[section]
            day = _day(row.get(field))
            used_fallback_date = section == "invoices" and day is None
            if used_fallback_date:
                day = _day(row.get("create_date"))
            linked = (section == "medical_cards" and row.get("admission_id") is not None
                      and str(row["admission_id"]) in linked_admission_ids)
            include = day is None or start <= day <= end or linked
            uncertain = day is None
        if include:
            selected.append(_project(section, row))
            if section == "invoices" and used_fallback_date and day is not None:
                gaps.append(f"invoices:{row.get('id')}:invoice_date_unknown_used_create_date")
            if uncertain:
                gaps.append(f"{section}:{row.get('id')}:unknown_date_boundary")
            if section == "medical_cards":
                description = row.get("description")
                if isinstance(description, str) and re.search(
                    r"<(?:a|img)\b[^>]*\b(?:href|src)\s*=", description, re.I
                ):
                    gaps.append(f"medical_cards:{row.get('id')}:attachment_unread")
                if _diagnosis_title_unresolved(row):
                    gaps.append(f"medical_cards:{row.get('id')}:diagnosis_title_unresolved")
    return selected, gaps


async def _scan(vc: VetmanagerClient, endpoint: str, key: str, filters: list[dict],
                page_size: int, request_budget: list[int] | None = None) -> tuple[list[dict], list[str]]:
    records, gaps, seen = [], [], set()
    expected = None
    for page in range(_PAGE_CAP):
        if request_budget is not None:
            if request_budget[0] >= _INVOICE_LINE_REQUEST_CAP:
                gaps.append(f"{key}:request_budget_exhausted")
                break
            request_budget[0] += 1
        offset = page * page_size
        try:
            response = await vc.get(endpoint, params=build_list_query_params(
                limit=page_size, offset=offset,
                sort=[{"property": "id", "direction": "ASC"}], filters=filters))
            data = response.get("data") if isinstance(response, dict) and response.get("success") is not False else None
            if isinstance(data, dict):
                rows = data.get(key)
                if rows is None and key == "medicalCards":
                    rows = data.get("medicalcards")
                if rows is None and key == "admission":
                    rows = data.get("admissions")
            else:
                rows = data if key == "admission" and isinstance(data, list) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise reportable_error("invalid list envelope")
            raw_total = data.get("totalCount") if isinstance(data, dict) else None
            total = int(raw_total) if raw_total is not None and str(raw_total).isdecimal() else None
            if expected is None:
                expected = total
                if total is None:
                    gaps.append(f"{key}:unknown_totalCount")
            elif total is not None and total != expected:
                gaps.append(f"{key}:changed_totalCount")
            cap_hit = False
            for row in rows:
                identity = row.get("id")
                if identity in seen or identity is None:
                    gaps.append(f"{key}:duplicate_or_missing_id")
                    continue
                if len(records) >= _ROW_CAP:
                    cap_hit = True
                    break
                seen.add(identity)
                records.append(row)
            if cap_hit or (len(records) >= _ROW_CAP and (expected is None or expected > _ROW_CAP)):
                gaps.append(f"{key}:row_cap_reached")
                break
            if expected is not None and len(records) > expected:
                gaps.append(f"{key}:totalCount_below_fetched")
            if expected is not None and len(records) >= expected:
                break
            if not rows:
                if expected is not None and len(records) < expected:
                    gaps.append(f"{key}:ended_before_totalCount")
                break
            if len(rows) < page_size:
                if expected is not None and len(records) < expected:
                    gaps.append(f"{key}:short_page_before_totalCount")
                break
        except Exception:
            gaps.append(f"{key}:read_failed_at_page_{page + 1}")
            break
    else:
        gaps.append(f"{key}:page_cap_reached")
    return records, gaps


def _section(records: list[dict], gaps: list[str]) -> dict:
    return {"records": records, "count": len(records), "complete": not gaps, "gaps": gaps}


def _owned(rows: list[dict], field: str, expected: int, section: str) -> tuple[list[dict], list[str]]:
    valid = [row for row in rows if str(row.get(field)) == str(expected)]
    return valid, ([f"{section}:upstream_parent_filter_mismatch"] if len(valid) != len(rows) else [])


async def fetch_history(pet_id: int, date_from: str, date_to: str, *,
                        finance_allowed: bool, page_size: int = 100) -> dict:
    if type(pet_id) is not int or pet_id <= 0:
        raise ToolInputError("pet_id must be a positive integer")
    start, end = _day(date_from), _day(date_to)
    if start is None or end is None or len(date_from) != 10 or len(date_to) != 10 or start > end:
        raise ToolInputError("date_from/date_to must be YYYY-MM-DD in ascending order")
    if not 1 <= page_size <= 100:
        raise ToolInputError("page_size must be 1..100")
    vc = VetmanagerClient()
    result = {"pet_id": pet_id, "date_from": date_from, "date_to": date_to,
              "period_basis": "clinic-local calendar dates in Vetmanager timestamps",
              "gaps": []}
    try:
        response = await vc.get(f"/rest/api/pet/{pet_id}")
        if not isinstance(response, dict) or response.get("success") is False:
            raise reportable_error("invalid pet response")
        pet = response.get("data", {}).get("pet")
        if not isinstance(pet, dict) or str(pet.get("id")) != str(pet_id):
            raise reportable_error("pet response mismatch")
        result["pet"] = _section([_project("pet", pet)], [])
    except Exception:
        result["pet"] = _section([], ["pet:read_failed"])
    for section in ("admissions", "medical_cards", "hospitalizations"):
        endpoint, key, id_field = _ENDPOINTS[section]
        rows, gaps = await _scan(vc, endpoint, key, [eq(id_field, pet_id)], page_size)
        rows, ownership_gaps = _owned(rows, id_field, pet_id, section)
        gaps += ownership_gaps
        result[section] = _section(rows, gaps)
    patient_card_ids = {str(row["id"]) for row in result["medical_cards"]["records"] if row.get("id") is not None}
    admissions, gaps = _select_period("admissions", result["admissions"]["records"], start, end, set())
    result["admissions"] = _section(admissions, result["admissions"]["gaps"] + gaps)
    admission_ids = {str(row["id"]) for row in admissions if row.get("id") is not None}
    for section in ("medical_cards", "hospitalizations"):
        selected, gaps = _select_period(section, result[section]["records"], start, end, admission_ids)
        result[section] = _section(selected, result[section]["gaps"] + gaps)
    await _add_vaccinations(vc, result, pet_id, start, end, patient_card_ids)
    await _add_invoices(vc, result, pet_id, start, end, page_size, finance_allowed)
    result["gaps"] = [gap for section in ("pet", "admissions", "medical_cards", "hospitalizations", "vaccinations", "invoices")
                      for gap in result[section]["gaps"]]
    result["complete"] = not result["gaps"]
    result["note"] = "Source records only. Agent drafts text and shows gaps. Saving is optional and separate."
    return result


async def _add_vaccinations(vc: VetmanagerClient, result: dict, pet_id: int,
                            start: date, end: date, patient_card_ids: set[str]) -> None:
    try:
        response = await vc.get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": pet_id, "limit": 100})
        if not isinstance(response, dict) or response.get("success") is False:
            raise reportable_error("invalid vaccination response")
        data = response.get("data", {})
        rows = data.get("medicalcards")
        if not isinstance(rows, list):
            raise reportable_error("invalid vaccination envelope")
        gaps = ["vaccinations:upstream_limit_exceeded"] if len(rows) > 100 else []
        rows = rows[:100]
        verified = [row for row in rows if isinstance(row, dict) and (
            row.get("medcard_id") is not None or row.get("pet_id") is not None
        ) and (
            row.get("medcard_id") is None or str(row["medcard_id"]) in patient_card_ids
        ) and (
            row.get("pet_id") is None or str(row["pet_id"]) == str(pet_id)
        )]
        ownership_gaps = (["vaccinations:patient_link_unverified"] if len(verified) != len(rows) else [])
        selected, period_gaps = _select_period("vaccinations", verified, start, end, set())
        gaps += period_gaps
        gaps += ownership_gaps
        total = data.get("totalCount")
        if total is None or not str(total).isdecimal() or int(total) != len(rows) or len(rows) >= 100:
            gaps.append("vaccinations:unpageable_or_unknown_total")
        result["vaccinations"] = _section(selected, gaps)
    except Exception:
        result["vaccinations"] = _section([], ["vaccinations:read_failed"])


async def _add_invoices(vc: VetmanagerClient, result: dict, pet_id: int,
                        start: date, end: date, page_size: int, allowed: bool) -> None:
    evidence_kind = "accounting_records_not_proof_of_treatment"
    if not allowed:
        result["invoices"] = _section([], ["invoices:finance.read_required"])
        result["invoices"]["evidence_kind"] = evidence_kind
        result["invoices"]["interpretation"] = "Invoice lines are accounting records, not proof that treatment was performed."
        return
    endpoint, key, id_field = _ENDPOINTS["invoices"]
    rows, gaps = await _scan(vc, endpoint, key, [eq(id_field, pet_id)], page_size)
    rows, ownership_gaps = _owned(rows, id_field, pet_id, "invoices")
    gaps += ownership_gaps
    selected, period_gaps = _select_period("invoices", rows, start, end, set())
    gaps += period_gaps
    line_budget = [0]
    for invoice in selected:
        raw_id = invoice.get("id")
        if (isinstance(raw_id, bool) or not isinstance(raw_id, (int, str))
                or not str(raw_id).isdecimal() or int(raw_id) <= 0):
            gaps.append("invoice_documents:invoice_id_unknown")
            continue
        invoice_id = int(raw_id)
        lines, line_gaps = await _scan(vc, "/rest/api/invoiceDocument", "invoiceDocument",
                                       [eq("document_id", invoice_id)], page_size, line_budget)
        lines, ownership_gaps = _owned(lines, "document_id", invoice_id, "invoice_documents")
        invoice["invoice_documents"] = [_project("invoice_documents", row) for row in lines]
        gaps.extend(f"invoice_{invoice_id}:{gap}" for gap in line_gaps + ownership_gaps)
    result["invoices"] = _section(selected, gaps)
    result["invoices"]["evidence_kind"] = evidence_kind
    result["invoices"]["interpretation"] = "Invoice lines are accounting records, not proof that treatment was performed."


def register(mcp):
    @mcp.tool
    async def get_pet_discharge_history(pet_id: int, date_from: str, date_to: str) -> dict:
        """Read source history for one patient's discharge draft over an inclusive period.

        Returns admissions, medical cards (diagnoses, treatment), vaccinations,
        hospitalizations, and invoice services when finance.read is granted.
        Invoice services are accounting records, not proof of treatment performed.
        Each section marks gaps; the agent writes the draft and shows them.
        Nothing is saved. Only after the user explicitly confirms the full
        text, offer the existing create_medical_card tool as an option if
        they separately want to save it.
        Domain synonyms: выписка, история болезни, история пациента, медкарта.
        """
        credentials = get_current_runtime_credentials()
        finance_allowed = credentials is not None and SCOPE_FINANCE_READ in credentials.scopes
        return await fetch_history(pet_id, date_from, date_to, finance_allowed=finance_allowed)

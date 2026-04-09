"""Shared helpers for inactive clients/pets tools.

Provides:
- calculate_inactive_window: calendar-accurate cutoff date math
- fetch_inactive_clients_page: single API call returning top N inactive clients
- find_pets_at_client_last_visit: per-pet visit detection via invoice→medcard
"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta

from vetmanager_client import VetmanagerClient


def calculate_inactive_window(
    months_min: int,
    months_max: int,
    *,
    today: date | None = None,
) -> tuple[str, str]:
    """Calendar-accurate window for last_visit_date filtering.

    Args:
        months_min: Minimum age of last visit in months (default 13).
        months_max: Maximum age of last visit in months (default 24).
        today: Reference date (default: today). Used for testing.

    Returns:
        (cutoff_oldest, cutoff_newest) as ISO date strings (YYYY-MM-DD).
        - cutoff_oldest = today - months_max  (last_visit_date >= this)
        - cutoff_newest = today - months_min  (last_visit_date <= this)

    Raises:
        ValueError: if months_min < 1 or months_min > months_max.
    """
    if months_min < 1:
        raise ValueError(f"months_min must be >= 1, got {months_min}")
    if months_min > months_max:
        raise ValueError(
            f"months_min must be <= months_max, got {months_min} > {months_max}"
        )

    ref = today or date.today()
    cutoff_oldest = _subtract_months(ref, months_max)
    cutoff_newest = _subtract_months(ref, months_min)
    return cutoff_oldest.isoformat(), cutoff_newest.isoformat()


def _subtract_months(d: date, months: int) -> date:
    """Subtract N months from a date with calendar-aware day clamping."""
    year = d.year
    month = d.month - months
    while month < 1:
        month += 12
        year -= 1
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, max_day))


async def fetch_inactive_clients_page(
    months_min: int,
    months_max: int,
    *,
    limit: int,
    offset: int = 0,
    today: date | None = None,
) -> tuple[list[dict], str, str]:
    """Fetch a page of inactive clients sorted by last_visit_date DESC.

    Single API call to /rest/api/client with filters:
        - status = ACTIVE
        - last_visit_date >= cutoff_oldest
        - last_visit_date <= cutoff_newest
    Sort: last_visit_date DESC (most recently lapsed first).

    Args:
        offset: Pagination offset to fetch deeper pages when accumulating
            pets requires scanning more clients than `limit`.

    Returns:
        (clients_list, cutoff_oldest, cutoff_newest)
    """
    cutoff_oldest, cutoff_newest = calculate_inactive_window(
        months_min, months_max, today=today
    )

    filters = [
        {"property": "status", "value": "ACTIVE", "operator": "="},
        {"property": "last_visit_date", "value": cutoff_oldest, "operator": ">="},
        {"property": "last_visit_date", "value": cutoff_newest, "operator": "<="},
    ]
    sort = [{"property": "last_visit_date", "direction": "DESC"}]

    params = {
        "limit": limit,
        "offset": offset,
        "filter": json.dumps(filters, separators=(",", ":"), ensure_ascii=False),
        "sort": json.dumps(sort, separators=(",", ":"), ensure_ascii=False),
    }
    resp = await VetmanagerClient().get("/rest/api/client", params=params)
    data = resp.get("data", {}) if isinstance(resp, dict) else {}
    if isinstance(data, dict):
        clients = data.get("client", []) or []
    else:
        clients = []
    return clients, cutoff_oldest, cutoff_newest


def _normalize_to_midnight(last_visit_date: str) -> str:
    """Convert 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD' to 'YYYY-MM-DD 00:00:00'."""
    date_part = last_visit_date.split(" ")[0] if last_visit_date else ""
    return f"{date_part} 00:00:00" if date_part else ""


def _next_day_midnight(last_visit_date: str) -> str:
    """Return the start of the day AFTER last_visit_date as 'YYYY-MM-DD 00:00:00'."""
    date_part = last_visit_date.split(" ")[0] if last_visit_date else ""
    if not date_part:
        return ""
    try:
        d = datetime.strptime(date_part, "%Y-%m-%d").date()
    except ValueError:
        return ""
    return f"{(d + timedelta(days=1)).isoformat()} 00:00:00"


async def find_pets_at_client_last_visit(
    vc: VetmanagerClient,
    *,
    client_id: int,
    last_visit_date: str,
) -> list[dict]:
    """Find pets that were at the client's last visit.

    Algorithm:
    1. Get all alive pets of this client (filter: owner_id, status=alive)
    2. For each pet, check invoices: filter[pet_id, invoice_date>=cutoff_00:00:00]
       - If invoice exists → pet was at the visit, source='invoice'
    3. For pets WITHOUT invoice match, check medcards as fallback:
       filter[patient_id, date_create>=cutoff_00:00:00]
       - If medcard exists → pet was at the visit, source='medcard'

    Args:
        vc: Active VetmanagerClient instance.
        client_id: Client ID to check pets for.
        last_visit_date: Client's last_visit_date (any format).

    Returns:
        List of pet dicts with extra 'visit_source' key ('invoice' or 'medcard').
        Pets that did not visit are excluded.
    """
    cutoff_start = _normalize_to_midnight(last_visit_date)
    cutoff_end = _next_day_midnight(last_visit_date)
    if not cutoff_start or not cutoff_end:
        return []

    # Step 1: get all alive pets of this client
    pet_filters = [
        {"property": "owner_id", "value": client_id, "operator": "="},
        {"property": "status", "value": "alive", "operator": "="},
    ]
    pet_params = {
        "limit": 100,
        "offset": 0,
        "filter": json.dumps(pet_filters, separators=(",", ":"), ensure_ascii=False),
    }
    pet_resp = await vc.get("/rest/api/pet", params=pet_params)
    pet_data = pet_resp.get("data", {}) if isinstance(pet_resp, dict) else {}
    pets = pet_data.get("pet", []) if isinstance(pet_data, dict) else []

    pet_ids = [pet.get("id") for pet in pets if pet.get("id") is not None]
    if not pet_ids:
        return []
    pet_by_id = {pet["id"]: pet for pet in pets if pet.get("id") is not None}

    # Step 2: batch-check invoices for ALL pets in a single request using
    # IN operator on pet_id. Same strict day-bounded window avoids false
    # positives from later backfilled records.
    inv_filters = [
        {"property": "pet_id", "value": pet_ids, "operator": "IN"},
        {"property": "invoice_date", "value": cutoff_start, "operator": ">="},
        {"property": "invoice_date", "value": cutoff_end, "operator": "<"},
    ]
    inv_params = {
        "limit": 100,
        "offset": 0,
        "filter": json.dumps(inv_filters, separators=(",", ":"), ensure_ascii=False),
    }
    inv_resp = await vc.get("/rest/api/invoice", params=inv_params)
    inv_data = inv_resp.get("data", {}) if isinstance(inv_resp, dict) else {}
    invoices = inv_data.get("invoice", []) if isinstance(inv_data, dict) else []

    visited: list[dict] = []
    pets_with_invoice: set = set()
    for inv in invoices:
        pid = inv.get("pet_id")
        try:
            pid_int = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid_int = None
        if pid_int is None or pid_int in pets_with_invoice:
            continue
        pet = pet_by_id.get(pid_int)
        if pet is None:
            continue
        pets_with_invoice.add(pid_int)
        visited.append({**pet, "visit_source": "invoice"})

    # Step 3: fallback to medical cards for pets WITHOUT an invoice match.
    # Batched with IN operator, same window.
    remaining_ids = [pid for pid in pet_ids if pid not in pets_with_invoice]
    if not remaining_ids:
        return visited

    mc_filters = [
        {"property": "patient_id", "value": remaining_ids, "operator": "IN"},
        {"property": "date_create", "value": cutoff_start, "operator": ">="},
        {"property": "date_create", "value": cutoff_end, "operator": "<"},
    ]
    mc_params = {
        "limit": 100,
        "offset": 0,
        "filter": json.dumps(mc_filters, separators=(",", ":"), ensure_ascii=False),
    }
    mc_resp = await vc.get("/rest/api/MedicalCards", params=mc_params)
    mc_data = mc_resp.get("data", {}) if isinstance(mc_resp, dict) else {}
    medcards = mc_data.get("medicalCards", []) if isinstance(mc_data, dict) else []
    if not medcards and isinstance(mc_data, dict):
        medcards = mc_data.get("medicalcards", []) or []

    pets_with_medcard: set = set()
    for mc in medcards:
        pid = mc.get("patient_id")
        try:
            pid_int = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid_int = None
        if pid_int is None or pid_int in pets_with_medcard:
            continue
        pet = pet_by_id.get(pid_int)
        if pet is None:
            continue
        pets_with_medcard.add(pid_int)
        visited.append({**pet, "visit_source": "medcard"})

    return visited

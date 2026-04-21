"""Shared helpers for inactive clients/pets tools.

Provides:
- calculate_inactive_window: calendar-accurate cutoff date math
- fetch_inactive_clients_page: single API call returning top N inactive clients
- find_pets_at_client_last_visit: per-pet visit detection via invoice→medcard
"""

from __future__ import annotations

import asyncio
import calendar
from datetime import date, datetime, timedelta

from filters import (
    build_list_query_params,
    eq as _filter_eq,
    gte as _filter_gte,
    in_ as _filter_in,
    lt as _filter_lt,
    lte as _filter_lte,
)
from vetmanager_client import VetmanagerClient

_BATCH_SIZE = 100
_BATCH_CONCURRENCY = 4


def _chunked(values: list[int], size: int = _BATCH_SIZE) -> list[list[int]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


async def _gather_bounded(*coroutines, limit: int | None = None) -> list:
    if not coroutines:
        return []
    semaphore = asyncio.Semaphore(limit or _BATCH_CONCURRENCY)

    async def _run(coroutine):
        async with semaphore:
            return await coroutine

    return await asyncio.gather(*[_run(coroutine) for coroutine in coroutines])


async def _fetch_all_entity_pages(
    vc: VetmanagerClient,
    *,
    endpoint: str,
    entity_keys: tuple[str, ...],
    filters: list,
) -> list[dict]:
    records: list[dict] = []
    offset = 0
    while True:
        params = build_list_query_params(
            limit=_BATCH_SIZE,
            offset=offset,
            filters=filters,
        )
        response = await vc.get(endpoint, params=params)
        data = response.get("data", {}) if isinstance(response, dict) else {}
        page_records: list[dict] = []
        if isinstance(data, dict):
            for key in entity_keys:
                candidate = data.get(key)
                if candidate:
                    page_records = candidate
                    break
        if not page_records:
            break
        records.extend(page_records)
        page_total = int(data.get("totalCount", 0)) if isinstance(data, dict) else 0
        offset += len(page_records)
        if page_total and offset >= page_total:
            break
        if len(page_records) < _BATCH_SIZE:
            break
    return records


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
        _filter_eq("status", "ACTIVE"),
        _filter_gte("last_visit_date", cutoff_oldest),
        _filter_lte("last_visit_date", cutoff_newest),
    ]
    sort = [{"property": "last_visit_date", "direction": "DESC"}]

    params = build_list_query_params(
        limit=limit,
        offset=offset,
        sort=sort,
        filters=filters,
    )
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

    # Step 1: get all alive pets of this client (may exceed the API page size).
    pet_filters = [_filter_eq("owner_id", client_id), _filter_eq("status", "alive")]
    pets: list[dict] = []
    offset = 0
    while True:
        pet_params = build_list_query_params(
            limit=_BATCH_SIZE,
            offset=offset,
            filters=pet_filters,
        )
        pet_resp = await vc.get("/rest/api/pet", params=pet_params)
        pet_data = pet_resp.get("data", {}) if isinstance(pet_resp, dict) else {}
        page_pets = pet_data.get("pet", []) if isinstance(pet_data, dict) else []
        if not page_pets:
            break
        pets.extend(page_pets)
        if len(page_pets) < _BATCH_SIZE:
            break
        offset += len(page_pets)

    pet_ids = [pet.get("id") for pet in pets if pet.get("id") is not None]
    if not pet_ids:
        return []
    pet_by_id = {pet["id"]: pet for pet in pets if pet.get("id") is not None}

    # Step 2: batch-check invoices for ALL pets in a single request using
    # IN operator on pet_id. Same strict day-bounded window avoids false
    # positives from later backfilled records.
    async def _fetch_invoice_chunk(chunk: list[int]) -> list[dict]:
        inv_filters = [
            _filter_in("pet_id", chunk),
            _filter_gte("invoice_date", cutoff_start),
            _filter_lt("invoice_date", cutoff_end),
        ]
        return await _fetch_all_entity_pages(
            vc,
            endpoint="/rest/api/invoice",
            entity_keys=("invoice",),
            filters=inv_filters,
        )

    invoice_chunks = _chunked([int(pid) for pid in pet_ids])
    invoice_pages = await _gather_bounded(
        *[_fetch_invoice_chunk(chunk) for chunk in invoice_chunks]
    )
    invoices = [invoice for page in invoice_pages for invoice in page]

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

    async def _fetch_medcard_chunk(chunk: list[int]) -> list[dict]:
        mc_filters = [
            _filter_in("patient_id", chunk),
            _filter_gte("date_create", cutoff_start),
            _filter_lt("date_create", cutoff_end),
        ]
        return await _fetch_all_entity_pages(
            vc,
            endpoint="/rest/api/MedicalCards",
            entity_keys=("medicalCards", "medicalcards"),
            filters=mc_filters,
        )

    medcard_pages = await _gather_bounded(
        *[_fetch_medcard_chunk(chunk) for chunk in _chunked([int(pid) for pid in remaining_ids])]
    )
    medcards = [medcard for page in medcard_pages for medcard in page]

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


async def find_pets_for_clients_last_visit(
    vc: VetmanagerClient,
    *,
    clients: list[dict],
    limit: int | None = None,
) -> list[tuple[dict, list[dict]]]:
    """Resolve pets for a client page with owner/date batching and stable order."""
    clients_with_visit = [
        client
        for client in clients
        if client.get("id") is not None and client.get("last_visit_date")
    ]
    if not clients_with_visit:
        return [(client, []) for client in clients]

    clients_by_day: dict[str, list[dict]] = {}
    for client in clients_with_visit:
        day_key = client["last_visit_date"].split(" ")[0]
        clients_by_day.setdefault(day_key, []).append(client)

    visited_pets_by_client: dict[int, list[dict]] = {}

    async def _fetch_pet_chunk(owner_ids: list[int]) -> list[dict]:
        pets: list[dict] = []
        offset = 0
        while True:
            pet_params = build_list_query_params(
                limit=_BATCH_SIZE,
                offset=offset,
                filters=[
                    _filter_in("owner_id", owner_ids),
                    _filter_eq("status", "alive"),
                ],
            )
            pet_resp = await vc.get("/rest/api/pet", params=pet_params)
            pet_data = pet_resp.get("data", {}) if isinstance(pet_resp, dict) else {}
            page_pets = pet_data.get("pet", []) if isinstance(pet_data, dict) else []
            if not page_pets:
                break
            pets.extend(page_pets)
            page_total = int(pet_data.get("totalCount", 0)) if isinstance(pet_data, dict) else 0
            if len(owner_ids) > 1 and page_total and offset + len(page_pets) >= page_total:
                break
            if len(page_pets) < _BATCH_SIZE:
                break
            offset += len(page_pets)
        return pets

    async def _fetch_invoice_chunk(day_start: str, day_end: str, pet_ids: list[int]) -> list[dict]:
        return await _fetch_all_entity_pages(
            vc,
            endpoint="/rest/api/invoice",
            entity_keys=("invoice",),
            filters=[
                _filter_in("pet_id", pet_ids),
                _filter_gte("invoice_date", day_start),
                _filter_lt("invoice_date", day_end),
            ],
        )

    async def _fetch_medcard_chunk(day_start: str, day_end: str, pet_ids: list[int]) -> list[dict]:
        return await _fetch_all_entity_pages(
            vc,
            endpoint="/rest/api/MedicalCards",
            entity_keys=("medicalCards", "medicalcards"),
            filters=[
                _filter_in("patient_id", pet_ids),
                _filter_gte("date_create", day_start),
                _filter_lt("date_create", day_end),
            ],
        )

    for day_clients in clients_by_day.values():
        owner_ids = [int(client["id"]) for client in day_clients]
        pet_pages = await _gather_bounded(
            *[_fetch_pet_chunk(chunk) for chunk in _chunked(owner_ids)]
        )
        day_pets = [pet for page in pet_pages for pet in page if pet.get("id") is not None]
        pet_by_id = {int(pet["id"]): pet for pet in day_pets}
        pet_ids = list(pet_by_id.keys())
        if not pet_ids:
            continue

        day_start = _normalize_to_midnight(day_clients[0]["last_visit_date"])
        day_end = _next_day_midnight(day_clients[0]["last_visit_date"])
        invoice_pages = await _gather_bounded(
            *[_fetch_invoice_chunk(day_start, day_end, chunk) for chunk in _chunked(pet_ids)]
        )
        invoices = [invoice for page in invoice_pages for invoice in page]

        pets_with_invoice: set[int] = set()
        visited_by_client: dict[int, list[dict]] = {}
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
            owner_id = int(pet["owner_id"])
            pets_with_invoice.add(pid_int)
            visited_by_client.setdefault(owner_id, []).append(
                {**pet, "visit_source": "invoice"}
            )

        if limit is not None:
            invoice_total = sum(len(pets) for pets in visited_by_client.values())
            if invoice_total >= limit:
                for owner_id, pets in visited_by_client.items():
                    visited_pets_by_client[owner_id] = pets
                continue

        remaining_ids = [pid for pid in pet_ids if pid not in pets_with_invoice]
        if remaining_ids:
            medcard_pages = await _gather_bounded(
                *[
                    _fetch_medcard_chunk(day_start, day_end, chunk)
                    for chunk in _chunked(remaining_ids)
                ]
            )
            medcards = [medcard for page in medcard_pages for medcard in page]
            pets_with_medcard: set[int] = set()
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
                owner_id = int(pet["owner_id"])
                pets_with_medcard.add(pid_int)
                visited_by_client.setdefault(owner_id, []).append(
                    {**pet, "visit_source": "medcard"}
                )

        for owner_id, pets in visited_by_client.items():
            visited_pets_by_client[owner_id] = pets

    return [
        (client, visited_pets_by_client.get(int(client["id"]), []))
        if client.get("id") is not None
        else (client, [])
        for client in clients
    ]

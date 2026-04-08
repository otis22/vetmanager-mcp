"""Schedule / availability tools.

Stage 80: get_doctor_free_slots — computes free appointment windows for
a doctor by subtracting active admissions from timesheet work intervals.
"""

from datetime import date, datetime, timedelta

from fastmcp import FastMCP

from tools._slots_helpers import (
    compute_free_slots,
    parse_admission_length,
    parse_vm_datetime,
)
from tools.crud_helpers import paginate_all
from validators import parse_date_param


# Admission statuses that actually occupy a slot on the doctor's calendar.
# `deleted` and `not_approved` are excluded (cancelled or not yet confirmed draft).
ACTIVE_ADMISSION_STATUSES = (
    "save",
    "directed",
    "accepted",
    "in_treatment",
    "delayed",
    "not_confirmed",
)

# Admissions that START before the requested window can STILL overlap into
# it (e.g. a 2h procedure that began at 23:30 the previous day). We fetch
# them by widening the admission_date lower bound by this slack, then filter
# client-side by real overlap with the work window. 24h covers any
# realistic appointment length (longest observed procedures are under 8h).
_ADMISSION_BACK_SLACK = timedelta(hours=24)

# Safety cap on total rows fetched per entity to prevent runaway memory
# use if a doctor has an abnormally dense schedule over a 31-day window.
# 31 days × ~20 slots/day = ~620 admissions expected; cap at 5× headroom.
_MAX_ROWS_PER_ENTITY = 3000


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_doctor_free_slots(
        doctor_id: int,
        date_from: str = "today",
        date_to: str = "+7d",
        slot_minutes: int = 30,
        min_slot_minutes: int = 15,
        clinic_id: int = 0,
    ) -> dict:
        """Return free appointment windows for a doctor over a date range.

        Domain synonyms: свободные окна, свободное время, расписание врача,
        доступное время записи, свободные слоты, free slots, availability.

        Computed as (doctor's timesheet work intervals) MINUS (active
        admissions on the same doctor). Breaks and lunches are represented
        implicitly as gaps between adjacent timesheet rows for the same
        day — the algorithm handles them natively.

        Usage chain: first resolve the doctor via get_users(name="Иванова")
        to obtain doctor_id, then call this tool.

        Args:
            doctor_id: Required. Numeric user id of the doctor.
            date_from: Range start (YYYY-MM-DD or relative: today, +7d,
                -1w, +1m, ...). Default: today.
            date_to: Range end, inclusive (same accepted formats).
                Default: +7d (one week from today). Max range: 31 days.
            slot_minutes: Size of each returned slot in minutes (5–240,
                default 30). Used both to chunk free gaps and as the
                fallback duration for admissions whose admission_length
                is not set (stored as "00:00:00").
            min_slot_minutes: Drop gaps shorter than this (5–slot_minutes,
                default 15).
            clinic_id: Optional clinic filter. 0 = all clinics where the
                doctor works.

        Returns:
            {success, doctor_id, date_from, date_to, slot_minutes,
             total_slots, slots: [{start, end, duration_min, clinic_id}, ...]}
        """
        if doctor_id <= 0:
            raise ValueError(
                "doctor_id is required. Resolve the doctor first via "
                "get_users(name=...)."
            )
        if not (5 <= slot_minutes <= 240):
            raise ValueError("slot_minutes must be between 5 and 240")
        if not (5 <= min_slot_minutes <= slot_minutes):
            raise ValueError(
                "min_slot_minutes must be between 5 and slot_minutes"
            )

        resolved_from = parse_date_param(date_from)
        resolved_to = parse_date_param(date_to)
        if not resolved_from or not resolved_to:
            raise ValueError("date_from and date_to are required")

        start_date = date.fromisoformat(resolved_from)
        end_date = date.fromisoformat(resolved_to)
        if end_date < start_date:
            raise ValueError("date_to must be >= date_from")
        if (end_date - start_date).days > 31:
            raise ValueError("date range cannot exceed 31 days")

        # Window bounds (fetched datetime strings are inclusive-start,
        # exclusive-end: [window_start, window_end)).
        window_start = datetime.combine(start_date, datetime.min.time())
        window_end = datetime.combine(
            end_date + timedelta(days=1), datetime.min.time()
        )
        fetch_end_str = window_end.strftime("%Y-%m-%d %H:%M:%S")
        fetch_start_str = window_start.strftime("%Y-%m-%d %H:%M:%S")

        # --- Fetch timesheet rows for this doctor overlapping the window ---
        ts_filters: list[dict] = [
            {"property": "doctor_id", "value": doctor_id, "operator": "="},
            {
                "property": "begin_datetime",
                "value": fetch_end_str,
                "operator": "<",
            },
            {
                "property": "end_datetime",
                "value": fetch_start_str,
                "operator": ">",
            },
        ]
        if clinic_id:
            ts_filters.append(
                {"property": "clinic_id", "value": clinic_id, "operator": "="}
            )

        timesheet_rows, _ = await paginate_all(
            "/rest/api/timesheet",
            filters=ts_filters,
            page_size=100,
            entity_key="timesheet",
            max_rows=_MAX_ROWS_PER_ENTITY,
        )

        # --- Fetch active admissions, widened backward by _ADMISSION_BACK_SLACK ---
        # This catches long admissions that started just before the window
        # and still overlap into it (e.g. a 23:30 admission with 2h duration
        # extending into the next day). Client-side overlap filter below.
        adm_fetch_lower = window_start - _ADMISSION_BACK_SLACK
        adm_fetch_lower_str = adm_fetch_lower.strftime("%Y-%m-%d %H:%M:%S")

        adm_filters: list[dict] = [
            {"property": "user_id", "value": doctor_id, "operator": "="},
            {
                "property": "admission_date",
                "value": adm_fetch_lower_str,
                "operator": ">=",
            },
            {
                "property": "admission_date",
                "value": fetch_end_str,
                "operator": "<",
            },
        ]
        if clinic_id:
            adm_filters.append(
                {"property": "clinic_id", "value": clinic_id, "operator": "="}
            )

        admission_rows, _ = await paginate_all(
            "/rest/api/admission",
            filters=adm_filters,
            page_size=100,
            entity_key="admission",
            max_rows=_MAX_ROWS_PER_ENTITY,
        )

        # --- Build work intervals from timesheet, grouped by clinic_id ---
        clinics_seen: dict[int, list[tuple[datetime, datetime]]] = {}
        for row in timesheet_rows:
            try:
                begin = parse_vm_datetime(row["begin_datetime"])
                end = parse_vm_datetime(row["end_datetime"])
            except (KeyError, ValueError):
                continue
            if end <= begin:
                continue
            cid = int(row.get("clinic_id") or 0)
            clinics_seen.setdefault(cid, []).append((begin, end))

        # --- Build busy intervals (shared across clinics for the doctor) ---
        # Filter client-side: keep only admissions that truly overlap the
        # window. The wider fetch_lower catches long-running admissions that
        # started before the window and still extend into it.
        busy: list[tuple[datetime, datetime]] = []
        for row in admission_rows:
            status = row.get("status")
            if status not in ACTIVE_ADMISSION_STATUSES:
                continue
            try:
                adm_start = parse_vm_datetime(row["admission_date"])
            except (KeyError, ValueError):
                continue
            length = parse_admission_length(
                row.get("admission_length"), fallback_minutes=slot_minutes
            )
            adm_end = adm_start + length
            # Overlap: [adm_start, adm_end) ∩ [window_start, window_end) ≠ ∅
            if adm_end <= window_start or adm_start >= window_end:
                continue
            busy.append((adm_start, adm_end))

        # --- Compute free slots per clinic, then flatten ---
        all_slots: list[dict] = []
        for cid, work in sorted(clinics_seen.items()):
            free = compute_free_slots(
                work, busy, slot_minutes=slot_minutes,
                min_slot_minutes=min_slot_minutes,
            )
            for slot_start, slot_end in free:
                # Clip slots to the requested date range — a timesheet
                # that starts before or ends after the window shouldn't
                # leak out-of-range slots.
                clipped_start = max(slot_start, window_start)
                clipped_end = min(slot_end, window_end)
                if clipped_end - clipped_start < timedelta(minutes=min_slot_minutes):
                    continue
                duration = (clipped_end - clipped_start).total_seconds() / 60
                all_slots.append(
                    {
                        "start": clipped_start.isoformat(),
                        "end": clipped_end.isoformat(),
                        "duration_min": int(duration),
                        "clinic_id": cid,
                    }
                )

        all_slots.sort(key=lambda s: s["start"])

        return {
            "success": True,
            "doctor_id": doctor_id,
            "date_from": resolved_from,
            "date_to": resolved_to,
            "slot_minutes": slot_minutes,
            "total_slots": len(all_slots),
            "slots": all_slots,
        }

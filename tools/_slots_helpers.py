"""Pure helpers for computing free appointment windows.

Used by `get_doctor_free_slots`. Works on absolute datetime intervals so
it correctly handles shifts that cross midnight (night shifts) and
multi-row timesheets where breaks/lunch are implicit gaps between rows.

No network I/O — all functions take pre-fetched intervals as input.
"""

from __future__ import annotations

from datetime import datetime, timedelta

Interval = tuple[datetime, datetime]


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    """Sort and merge overlapping/touching intervals into a minimal list.

    Adjacent intervals (a.end == b.start) are merged. Empty list → [].
    """
    if not intervals:
        return []
    valid = [(s, e) for s, e in intervals if e > s]
    valid.sort(key=lambda iv: iv[0])
    merged: list[Interval] = []
    for start, end in valid:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def subtract_intervals(
    work: list[Interval],
    busy: list[Interval],
) -> list[Interval]:
    """Return `work` minus `busy`. Both lists are merged first.

    Each resulting gap is a sub-interval of some work interval that is
    not covered by any busy interval.
    """
    work = merge_intervals(work)
    busy = merge_intervals(busy)
    if not work:
        return []
    if not busy:
        return list(work)

    result: list[Interval] = []
    for w_start, w_end in work:
        cursor = w_start
        for b_start, b_end in busy:
            if b_end <= cursor:
                continue  # busy before cursor
            if b_start >= w_end:
                break  # busy past this work interval
            # Clip busy into the work window.
            clipped_start = max(b_start, cursor)
            clipped_end = min(b_end, w_end)
            if clipped_start > cursor:
                result.append((cursor, clipped_start))
            cursor = max(cursor, clipped_end)
            if cursor >= w_end:
                break
        if cursor < w_end:
            result.append((cursor, w_end))
    return result


def chunk_into_slots(
    gap: Interval,
    slot_minutes: int,
    min_slot_minutes: int,
) -> list[Interval]:
    """Split a single free gap into fixed-size slots.

    The final slot may be shorter than `slot_minutes` but must be at
    least `min_slot_minutes` to be returned. Short leftovers are dropped.
    """
    start, end = gap
    total = (end - start).total_seconds() / 60
    if total < min_slot_minutes:
        return []

    slots: list[Interval] = []
    cursor = start
    step = timedelta(minutes=slot_minutes)
    while cursor + step <= end:
        slots.append((cursor, cursor + step))
        cursor += step
    leftover_min = (end - cursor).total_seconds() / 60
    if leftover_min >= min_slot_minutes:
        slots.append((cursor, end))
    return slots


def compute_free_slots(
    work_intervals: list[Interval],
    busy_intervals: list[Interval],
    slot_minutes: int,
    min_slot_minutes: int,
) -> list[Interval]:
    """High-level: subtract busy from work, then chunk each gap into slots.

    Returns a flat list of (start, end) datetime tuples sorted ascending.
    """
    if slot_minutes <= 0:
        raise ValueError("slot_minutes must be > 0")
    if min_slot_minutes <= 0 or min_slot_minutes > slot_minutes:
        raise ValueError(
            "min_slot_minutes must be in (0, slot_minutes]"
        )
    gaps = subtract_intervals(work_intervals, busy_intervals)
    slots: list[Interval] = []
    for gap in gaps:
        slots.extend(chunk_into_slots(gap, slot_minutes, min_slot_minutes))
    return slots


def parse_admission_length(raw: str | None, fallback_minutes: int) -> timedelta:
    """Parse a Vetmanager admission_length string (HH:MM:SS) to timedelta.

    Returns `fallback_minutes` as timedelta if raw is None, empty, or the
    sentinel "00:00:00" (meaning the clinic did not set a specific length).
    """
    if not raw or raw == "00:00:00":
        return timedelta(minutes=fallback_minutes)
    try:
        h, m, s = raw.split(":")
        td = timedelta(hours=int(h), minutes=int(m), seconds=int(s))
    except (ValueError, AttributeError):
        return timedelta(minutes=fallback_minutes)
    if td.total_seconds() <= 0:
        return timedelta(minutes=fallback_minutes)
    return td


def parse_vm_datetime(raw: str) -> datetime:
    """Parse a Vetmanager datetime string 'YYYY-MM-DD HH:MM:SS' to naive datetime.

    Vetmanager returns timestamps in the clinic's local timezone; we keep
    them naive throughout the slot calculation (no TZ conversion).
    """
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")

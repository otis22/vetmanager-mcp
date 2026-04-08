"""Unit tests for pure slot-computation helpers (Stage 80)."""

from datetime import datetime, timedelta

import pytest

from tools._slots_helpers import (
    chunk_into_slots,
    compute_free_slots,
    merge_intervals,
    parse_admission_length,
    parse_vm_datetime,
    subtract_intervals,
)


def dt(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s)


# ── merge_intervals ──────────────────────────────────────────────────────────


class TestMergeIntervals:
    def test_empty(self):
        assert merge_intervals([]) == []

    def test_single(self):
        iv = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 12))]
        assert merge_intervals(iv) == iv

    def test_non_overlapping(self):
        a = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12))
        b = (dt(2026, 4, 10, 14), dt(2026, 4, 10, 18))
        assert merge_intervals([a, b]) == [a, b]

    def test_overlapping(self):
        a = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12))
        b = (dt(2026, 4, 10, 11), dt(2026, 4, 10, 15))
        assert merge_intervals([a, b]) == [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 15))]

    def test_touching(self):
        a = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12))
        b = (dt(2026, 4, 10, 12), dt(2026, 4, 10, 15))
        assert merge_intervals([a, b]) == [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 15))]

    def test_unsorted_input(self):
        a = (dt(2026, 4, 10, 14), dt(2026, 4, 10, 18))
        b = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12))
        assert merge_intervals([a, b]) == [b, a]

    def test_drops_zero_length(self):
        z = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9))
        a = (dt(2026, 4, 10, 10), dt(2026, 4, 10, 11))
        assert merge_intervals([z, a]) == [a]


# ── subtract_intervals ───────────────────────────────────────────────────────


class TestSubtract:
    def test_no_busy(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        assert subtract_intervals(work, []) == work

    def test_no_work(self):
        busy = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        assert subtract_intervals([], busy) == []

    def test_busy_covers_whole_work(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        busy = [(dt(2026, 4, 10, 8), dt(2026, 4, 10, 20))]
        assert subtract_intervals(work, busy) == []

    def test_busy_at_start(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        busy = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 10))]
        assert subtract_intervals(work, busy) == [
            (dt(2026, 4, 10, 10), dt(2026, 4, 10, 18))
        ]

    def test_busy_at_end(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        busy = [(dt(2026, 4, 10, 17), dt(2026, 4, 10, 18))]
        assert subtract_intervals(work, busy) == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 17))
        ]

    def test_busy_in_middle(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        busy = [(dt(2026, 4, 10, 12), dt(2026, 4, 10, 13))]
        assert subtract_intervals(work, busy) == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12)),
            (dt(2026, 4, 10, 13), dt(2026, 4, 10, 18)),
        ]

    def test_two_busy_merged(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        busy = [
            (dt(2026, 4, 10, 12), dt(2026, 4, 10, 13)),
            (dt(2026, 4, 10, 15), dt(2026, 4, 10, 16)),
        ]
        assert subtract_intervals(work, busy) == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12)),
            (dt(2026, 4, 10, 13), dt(2026, 4, 10, 15)),
            (dt(2026, 4, 10, 16), dt(2026, 4, 10, 18)),
        ]

    def test_busy_outside_work(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        busy = [(dt(2026, 4, 9, 9), dt(2026, 4, 9, 12))]
        assert subtract_intervals(work, busy) == work

    def test_multi_row_timesheet_lunch_break(self):
        """Doctor with morning + afternoon shifts (implicit lunch)."""
        work = [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12, 30)),
            (dt(2026, 4, 10, 14), dt(2026, 4, 10, 18)),
        ]
        busy = [(dt(2026, 4, 10, 10), dt(2026, 4, 10, 11))]
        assert subtract_intervals(work, busy) == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 10)),
            (dt(2026, 4, 10, 11), dt(2026, 4, 10, 12, 30)),
            (dt(2026, 4, 10, 14), dt(2026, 4, 10, 18)),
        ]

    def test_night_shift_crossing_midnight(self):
        """Night shift 22:00 → next day 08:00 is a single continuous interval."""
        work = [(dt(2026, 4, 10, 22), dt(2026, 4, 11, 8))]
        busy = [(dt(2026, 4, 11, 2), dt(2026, 4, 11, 3))]
        assert subtract_intervals(work, busy) == [
            (dt(2026, 4, 10, 22), dt(2026, 4, 11, 2)),
            (dt(2026, 4, 11, 3), dt(2026, 4, 11, 8)),
        ]

    def test_busy_clipped_to_work_boundary(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 18))]
        busy = [(dt(2026, 4, 10, 8), dt(2026, 4, 10, 10))]
        assert subtract_intervals(work, busy) == [
            (dt(2026, 4, 10, 10), dt(2026, 4, 10, 18))
        ]


# ── chunk_into_slots ─────────────────────────────────────────────────────────


class TestChunk:
    def test_exact_fit(self):
        gap = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 10))
        assert chunk_into_slots(gap, 30, 15) == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9, 30)),
            (dt(2026, 4, 10, 9, 30), dt(2026, 4, 10, 10)),
        ]

    def test_leftover_returned(self):
        gap = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9, 45))
        # 2 slots @30m wouldn't fit; 1 full slot + 15m leftover (>=min) → 2 slots.
        assert chunk_into_slots(gap, 30, 15) == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9, 30)),
            (dt(2026, 4, 10, 9, 30), dt(2026, 4, 10, 9, 45)),
        ]

    def test_leftover_dropped(self):
        gap = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9, 40))
        # 1 slot @30m + 10m leftover (<min 15) → drop leftover.
        assert chunk_into_slots(gap, 30, 15) == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9, 30))
        ]

    def test_too_short_dropped(self):
        gap = (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9, 10))
        assert chunk_into_slots(gap, 30, 15) == []


# ── compute_free_slots (integration of the three) ────────────────────────────


class TestComputeFreeSlots:
    def test_empty_timesheet(self):
        assert compute_free_slots([], [], 30, 15) == []

    def test_no_admissions_full_day(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 11))]
        result = compute_free_slots(work, [], 30, 15)
        assert result == [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 9, 30)),
            (dt(2026, 4, 10, 9, 30), dt(2026, 4, 10, 10)),
            (dt(2026, 4, 10, 10), dt(2026, 4, 10, 10, 30)),
            (dt(2026, 4, 10, 10, 30), dt(2026, 4, 10, 11)),
        ]

    def test_fully_booked(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 10))]
        busy = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 10))]
        assert compute_free_slots(work, busy, 30, 15) == []

    def test_admission_outside_timesheet_ignored(self):
        work = [(dt(2026, 4, 10, 9), dt(2026, 4, 10, 10))]
        busy = [(dt(2026, 4, 10, 14), dt(2026, 4, 10, 15))]
        assert len(compute_free_slots(work, busy, 30, 15)) == 2

    def test_multi_row_with_lunch(self):
        work = [
            (dt(2026, 4, 10, 9), dt(2026, 4, 10, 12)),
            (dt(2026, 4, 10, 14), dt(2026, 4, 10, 17)),
        ]
        busy = []
        slots = compute_free_slots(work, busy, 60, 30)
        # 3 slots morning + 3 afternoon = 6
        assert len(slots) == 6

    def test_invalid_slot_minutes(self):
        with pytest.raises(ValueError):
            compute_free_slots([], [], 0, 15)

    def test_invalid_min_slot_minutes(self):
        with pytest.raises(ValueError):
            compute_free_slots([], [], 30, 31)


# ── parse_admission_length ───────────────────────────────────────────────────


class TestParseAdmissionLength:
    def test_normal(self):
        assert parse_admission_length("00:30:00", 15) == timedelta(minutes=30)

    def test_zero_fallback(self):
        assert parse_admission_length("00:00:00", 25) == timedelta(minutes=25)

    def test_none_fallback(self):
        assert parse_admission_length(None, 20) == timedelta(minutes=20)

    def test_empty_fallback(self):
        assert parse_admission_length("", 20) == timedelta(minutes=20)

    def test_malformed_fallback(self):
        assert parse_admission_length("abc", 20) == timedelta(minutes=20)

    def test_with_hours(self):
        assert parse_admission_length("01:30:00", 15) == timedelta(hours=1, minutes=30)


# ── parse_vm_datetime ────────────────────────────────────────────────────────


class TestParseVmDatetime:
    def test_basic(self):
        assert parse_vm_datetime("2026-04-10 09:00:00") == dt(2026, 4, 10, 9)

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_vm_datetime("2026-04-10T09:00:00")

"""Tests for tools/_inactive_helpers.py."""

from datetime import date

import pytest

from tools._inactive_helpers import calculate_inactive_window


class TestCalculateInactiveWindow:
    def test_default_window_13_to_24_months(self):
        # Use fixed reference date for determinism
        cutoff_oldest, cutoff_newest = calculate_inactive_window(
            months_min=13, months_max=24, today=date(2026, 4, 7)
        )
        # months_max=24 → cutoff_oldest = 2024-04-07
        assert cutoff_oldest == "2024-04-07"
        # months_min=13 → cutoff_newest = 2025-03-07
        assert cutoff_newest == "2025-03-07"

    def test_custom_window_3_to_6_months(self):
        cutoff_oldest, cutoff_newest = calculate_inactive_window(
            months_min=3, months_max=6, today=date(2026, 4, 7)
        )
        assert cutoff_oldest == "2025-10-07"
        assert cutoff_newest == "2026-01-07"

    def test_calendar_accurate_month_subtraction(self):
        # Today=March 31, subtract 1 month → February 28 (not March 3)
        cutoff_oldest, cutoff_newest = calculate_inactive_window(
            months_min=1, months_max=1, today=date(2025, 3, 31)
        )
        assert cutoff_oldest == "2025-02-28"
        assert cutoff_newest == "2025-02-28"

    def test_handles_leap_year_boundary(self):
        # Today=Feb 29 leap year, subtract 12 months → Feb 28 of prev year
        cutoff_oldest, _ = calculate_inactive_window(
            months_min=12, months_max=12, today=date(2024, 2, 29)
        )
        assert cutoff_oldest == "2023-02-28"

    def test_validates_min_less_than_or_equal_max(self):
        with pytest.raises(ValueError, match="months_min must be <= months_max"):
            calculate_inactive_window(months_min=10, months_max=5)

    def test_validates_positive_min(self):
        with pytest.raises(ValueError, match="months_min must be >= 1"):
            calculate_inactive_window(months_min=0, months_max=5)

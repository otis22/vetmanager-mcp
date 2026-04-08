"""Unit tests for validators.parse_date_param (Stage 79)."""

from datetime import date

import pytest

from validators import parse_date_param


FIXED = date(2026, 4, 8)  # Wednesday


class TestAbsolute:
    def test_iso_passthrough(self):
        assert parse_date_param("2026-04-08") == "2026-04-08"

    def test_iso_with_whitespace(self):
        assert parse_date_param("  2026-04-08  ") == "2026-04-08"

    def test_empty_returns_empty(self):
        assert parse_date_param("") == ""

    def test_whitespace_only_returns_empty(self):
        assert parse_date_param("   ") == ""


class TestKeywords:
    def test_today(self):
        assert parse_date_param("today", today=FIXED) == "2026-04-08"

    def test_yesterday(self):
        assert parse_date_param("yesterday", today=FIXED) == "2026-04-07"

    def test_tomorrow(self):
        assert parse_date_param("tomorrow", today=FIXED) == "2026-04-09"

    def test_case_insensitive(self):
        assert parse_date_param("TODAY", today=FIXED) == "2026-04-08"
        assert parse_date_param("Yesterday", today=FIXED) == "2026-04-07"


class TestRelativeDays:
    def test_plus_days(self):
        assert parse_date_param("+7d", today=FIXED) == "2026-04-15"

    def test_minus_days(self):
        assert parse_date_param("-7d", today=FIXED) == "2026-04-01"

    def test_zero_days(self):
        assert parse_date_param("+0d", today=FIXED) == "2026-04-08"

    def test_month_boundary(self):
        assert parse_date_param("+30d", today=FIXED) == "2026-05-08"


class TestRelativeWeeks:
    def test_plus_weeks(self):
        assert parse_date_param("+2w", today=FIXED) == "2026-04-22"

    def test_minus_weeks(self):
        assert parse_date_param("-1w", today=FIXED) == "2026-04-01"


class TestRelativeMonths:
    def test_plus_month(self):
        assert parse_date_param("+1m", today=FIXED) == "2026-05-08"

    def test_minus_month(self):
        assert parse_date_param("-1m", today=FIXED) == "2026-03-08"

    def test_plus_twelve_months(self):
        assert parse_date_param("+12m", today=FIXED) == "2027-04-08"

    def test_end_of_month_clamp_31_to_30(self):
        # Jan 31 + 1 month → Feb 28 (not Mar 3)
        assert parse_date_param("+1m", today=date(2026, 1, 31)) == "2026-02-28"

    def test_end_of_month_clamp_31_to_leap(self):
        # Jan 31 + 1 month in a leap year → Feb 29
        assert parse_date_param("+1m", today=date(2024, 1, 31)) == "2024-02-29"

    def test_end_of_month_clamp_31_to_30_april(self):
        # Mar 31 + 1 month → Apr 30
        assert parse_date_param("+1m", today=date(2026, 3, 31)) == "2026-04-30"

    def test_cross_year_boundary(self):
        # Dec 15 + 1 month → Jan 15 next year
        assert parse_date_param("+1m", today=date(2025, 12, 15)) == "2026-01-15"

    def test_minus_month_cross_year(self):
        assert parse_date_param("-1m", today=date(2026, 1, 15)) == "2025-12-15"

    def test_into_december_branch(self):
        # Nov 30 + 1m → Dec 30: exercises the `month == 12` branch of _add_months.
        assert parse_date_param("+1m", today=date(2025, 11, 30)) == "2025-12-30"

    def test_december_31_plus_1m(self):
        # Dec 31 + 1m → Jan 31 next year (no clamp needed, Jan has 31 days).
        assert parse_date_param("+1m", today=date(2025, 12, 31)) == "2026-01-31"


class TestInvalid:
    def test_unknown_keyword(self):
        with pytest.raises(ValueError, match="Supported formats"):
            parse_date_param("nextweek")

    def test_slash_format(self):
        with pytest.raises(ValueError):
            parse_date_param("2026/04/08")

    def test_years_not_supported(self):
        with pytest.raises(ValueError):
            parse_date_param("+1y")

    def test_missing_digits(self):
        with pytest.raises(ValueError):
            parse_date_param("+d")

    def test_invalid_iso(self):
        with pytest.raises(ValueError):
            parse_date_param("2026-13-45")

    def test_huge_relative_offset_rejected(self):
        with pytest.raises(ValueError, match="too large"):
            parse_date_param("+999999999d")

    def test_huge_month_offset_rejected(self):
        with pytest.raises(ValueError, match="too large"):
            parse_date_param("-999999m")

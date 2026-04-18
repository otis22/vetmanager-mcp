"""Input validation helpers for MCP tools.

Guards against accidental bulk operations caused by malformed prompts.
"""

import re
from datetime import date, timedelta
from typing import Annotated

from pydantic import Field

_LIMIT_MAX = 100
_OFFSET_MAX = 10_000
_AMOUNT_MAX = 1_000_000

VETMANAGER_MAX_LIMIT = _LIMIT_MAX

LimitParam = Annotated[
    int,
    Field(ge=1, le=_LIMIT_MAX, description="Max records to return (1–100)."),
]


def validate_list_params(limit: int, offset: int) -> None:
    """Validate pagination parameters for list endpoints.

    Raises:
        ValueError: If limit or offset are outside safe bounds.
    """
    if limit < 1 or limit > _LIMIT_MAX:
        raise ValueError(
            f"'limit' must be between 1 and {_LIMIT_MAX}, got {limit}. "
            "Use pagination (offset) to retrieve more records."
        )
    if offset < 0 or offset > _OFFSET_MAX:
        raise ValueError(
            f"'offset' must be between 0 and {_OFFSET_MAX}, got {offset}. "
            "If you need records beyond this range, refine your search criteria."
        )


_REL_DATE_PATTERN = re.compile(r"^([+-])(\d+)([dwm])$")
_SUPPORTED_DATE_FORMATS = (
    "YYYY-MM-DD, today, yesterday, tomorrow, "
    "+Nd/-Nd, +Nw/-Nw, +Nm/-Nm"
)
# Sane upper bounds for relative-date offsets. 20 years is plenty for any
# realistic clinic scheduling/reporting query and prevents OverflowError
# on absurdly large inputs like "+999999999m".
_MAX_REL_DAYS = 20 * 366
_MAX_REL_WEEKS = _MAX_REL_DAYS // 7
_MAX_REL_MONTHS = 20 * 12


def _add_months(base: date, months: int) -> date:
    """Add months to a date, clamping end-of-month.

    Example: 2026-01-31 + 1m → 2026-02-28 (not 2026-03-03).
    """
    # Calculate target month/year
    total_month = base.month - 1 + months
    year = base.year + total_month // 12
    month = total_month % 12 + 1
    # Clamp day to last day of target month
    if month == 12:
        last_day = 31
    else:
        last_day = (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(base.day, last_day))


def parse_date_param(value: str, *, today: date | None = None) -> str:
    """Convert a relative or absolute date spec to YYYY-MM-DD.

    Accepted forms (case-insensitive, whitespace-trimmed):
      - ""                  → "" (no filter)
      - "YYYY-MM-DD"        → passthrough after ISO validation
      - "today"             → today's local date
      - "yesterday"         → today - 1 day
      - "tomorrow"          → today + 1 day
      - "+Nd" / "-Nd"       → today ± N days
      - "+Nw" / "-Nw"       → today ± N weeks
      - "+Nm" / "-Nm"       → today ± N calendar months (end-of-month clamp)

    The API returns and accepts dates in the clinic's local timezone by
    default, so this helper works with naive local dates — no TZ conversion.

    Args:
        value: Raw user-supplied date string.
        today: Override the "current" date (for deterministic tests).

    Returns:
        ISO date string (YYYY-MM-DD), or empty string for empty input.

    Raises:
        ValueError: If `value` does not match any supported form.
    """
    if value is None or value == "":
        return ""

    s = value.strip().lower()
    if s == "":
        return ""

    anchor = today or date.today()

    if s == "today":
        return anchor.isoformat()
    if s == "yesterday":
        return (anchor - timedelta(days=1)).isoformat()
    if s == "tomorrow":
        return (anchor + timedelta(days=1)).isoformat()

    rel_match = _REL_DATE_PATTERN.match(s)
    if rel_match:
        sign, digits, unit = rel_match.groups()
        n = int(digits)
        caps = {"d": _MAX_REL_DAYS, "w": _MAX_REL_WEEKS, "m": _MAX_REL_MONTHS}
        if n > caps[unit]:
            raise ValueError(
                f"relative date offset too large: '{value}'. "
                f"Maximum: ±{caps[unit]}{unit}."
            )
        if sign == "-":
            n = -n
        try:
            if unit == "d":
                return (anchor + timedelta(days=n)).isoformat()
            if unit == "w":
                return (anchor + timedelta(weeks=n)).isoformat()
            if unit == "m":
                return _add_months(anchor, n).isoformat()
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                f"relative date '{value}' resolves outside representable range"
            ) from exc

    # Absolute ISO date.
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise ValueError(
            f"invalid date '{value}'. Supported formats: {_SUPPORTED_DATE_FORMATS}"
        ) from None


def normalize_phone_digits(raw: str) -> str:
    """Strip everything except digits from a phone string.

    Returns only decimal digits. Empty input returns empty string.
    Used for LIKE-style phone search where we want to ignore formatting
    (parentheses, spaces, dashes, leading +).
    """
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isdigit())


def validate_amount(amount: float) -> None:
    """Validate a monetary amount for payment operations.

    Raises:
        ValueError: If amount is not within a plausible range.
    """
    if amount <= 0 or amount > _AMOUNT_MAX:
        raise ValueError(
            f"'amount' must be greater than 0 and no more than {_AMOUNT_MAX:,}, "
            f"got {amount}. Verify the currency units (use roubles, not kopecks)."
        )


# Stage 103.8: `build_list_query_params` moved to filters.py (co-located with
# the Filter primitives it serializes). Re-exported here for BC — drop when
# all external callers migrate.
from filters import build_list_query_params  # noqa: E402,F401

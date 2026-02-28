"""Input validation helpers for MCP tools.

Guards against accidental bulk operations caused by malformed prompts.
"""

import json
from typing import Any

_LIMIT_MAX = 100
_OFFSET_MAX = 10_000
_AMOUNT_MAX = 1_000_000


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


def build_list_query_params(
    limit: int,
    offset: int,
    sort: list[dict[str, Any]] | None = None,
    filters: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build common list-query params with optional sort/filter blocks."""
    validate_list_params(limit, offset)
    params: dict[str, Any] = {"limit": limit, "offset": offset}

    if sort:
        params["sort"] = json.dumps(sort, separators=(",", ":"), ensure_ascii=False)
    if filters:
        params["filter"] = json.dumps(filters, separators=(",", ":"), ensure_ascii=False)

    if extra:
        for key, value in extra.items():
            if value is None or value == "":
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
                continue
            params[key] = value

    return params

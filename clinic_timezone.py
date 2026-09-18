"""Bounded clinic-timezone resolver shared by Report AI and MCP date tools."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timezone
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from observability_logging import RUNTIME_LOGGER
from runtime_auth import get_current_runtime_credentials
from vetmanager_client import VetmanagerClient

CLINIC_TIMEZONE_TTL_SECONDS = 3600
CLINIC_TIMEZONE_MAX_ENTRIES = 4096
_CACHE: OrderedDict[tuple[int | None, int | None, int], tuple[str | None, float]] = OrderedDict()


def _key(clinic_id: int) -> tuple[int | None, int | None, int]:
    credentials = get_current_runtime_credentials()
    return (
        credentials.account_id if credentials else None,
        credentials.connection_id if credentials else None,
        clinic_id,
    )


def reset_clinic_timezone_cache() -> None:
    _CACHE.clear()


def process_local_today() -> date:
    """Documented fallback for a multi-clinic call without a clinic id."""
    RUNTIME_LOGGER.warning("clinic_timezone_unavailable", extra={"event_name": "clinic_timezone_unavailable"})
    return date.today()


async def resolve_clinic_timezone(
    clinic_id: int | None, *, client_factory=None, monotonic=None
) -> ZoneInfo | None:
    """Return clinic-local date; explicit process-local fallback when unavailable.

    ``None``/non-positive clinic ids cannot identify a branch and deliberately
    use the process date. A missing or malformed upstream timezone is a bounded
    negative cache entry. Transport failures stay uncached so a later request
    can recover without waiting for TTL.
    """
    if not isinstance(clinic_id, int) or clinic_id <= 0:
        return None
    key = _key(clinic_id)
    monotonic_now = (monotonic or time.monotonic)()
    cached = _CACHE.get(key)
    if cached is not None and monotonic_now - cached[1] <= CLINIC_TIMEZONE_TTL_SECONDS:
        timezone_name = cached[0]
        _CACHE.move_to_end(key)
    else:
        _CACHE.pop(key, None)
        try:
            payload = await (client_factory or VetmanagerClient)().get(f"/rest/api/clinics/{clinic_id}")
        except Exception:
            RUNTIME_LOGGER.warning("clinic_timezone_unavailable", extra={"event_name": "clinic_timezone_unavailable"})
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        clinic = data.get("clinics") if isinstance(data, dict) else None
        if isinstance(clinic, list):
            clinic = clinic[0] if clinic else None
        timezone_name = clinic.get("time_zone") if isinstance(clinic, dict) else None
        if not isinstance(timezone_name, str) or not timezone_name:
            timezone_name = None
        _CACHE[key] = (timezone_name, monotonic_now)
        _CACHE.move_to_end(key)
        while len(_CACHE) > CLINIC_TIMEZONE_MAX_ENTRIES:
            _CACHE.popitem(last=False)
        if timezone_name is None:
            RUNTIME_LOGGER.warning("clinic_timezone_unavailable", extra={"event_name": "clinic_timezone_unavailable"})
    if not timezone_name:
        return None
    try:
        return ZoneInfo(timezone_name)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        RUNTIME_LOGGER.warning("clinic_timezone_invalid", extra={"event_name": "clinic_timezone_invalid"})
        return None


async def clinic_local_today(clinic_id: int | None, *, now: datetime | None = None) -> date:
    """Return clinic-local date, with the resolver's explicit process fallback."""
    clinic_timezone = await resolve_clinic_timezone(clinic_id)
    if clinic_timezone is None:
        return date.today()
    return (now or datetime.now(timezone.utc)).astimezone(clinic_timezone).date()

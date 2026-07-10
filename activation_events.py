"""Persisted activation product events for stage 198."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Mapping

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AuthError, HostResolutionError, VetmanagerError
from observability_logging import RUNTIME_LOGGER
from storage_models import (
    ACTIVATION_AUTH_MODES,
    ACTIVATION_COPY_KINDS,
    ACTIVATION_DEVICE_CLASSES,
    ACTIVATION_EVENT_NAMES,
    ACTIVATION_REASON_CLASSES,
    ActivationEvent,
)

ACTIVATION_EVENT_RETENTION_DAYS = 90
_CLEANUP_INTERVAL = timedelta(days=1)
_last_cleanup_at: datetime | None = None


def reset_activation_event_state() -> None:
    """Reset process-local cleanup throttle for tests."""
    global _last_cleanup_at
    _last_cleanup_at = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_activation_event_cleanup_due(
    *,
    now: datetime | None = None,
    force: bool = False,
) -> bool:
    """Return whether old activation events should be cleaned up now."""
    current = now or _now_utc()
    return bool(
        force
        or _last_cleanup_at is None
        or current - _last_cleanup_at >= _CLEANUP_INTERVAL
    )


def mark_activation_event_cleanup_succeeded(*, now: datetime | None = None) -> None:
    """Advance cleanup throttle after the caller has committed successfully."""
    global _last_cleanup_at
    _last_cleanup_at = now or _now_utc()


def _coerce(value: str | None, allowed: tuple[str, ...], default: str) -> str:
    if value in allowed:
        return str(value)
    return default


def classify_activation_device(headers: Mapping[str, str]) -> str:
    """Return a coarse device class without persisting raw User-Agent."""
    user_agent = ""
    for key, value in headers.items():
        if key.lower() == "user-agent":
            user_agent = value.lower()
            break
    if not user_agent:
        return "unknown"
    if any(marker in user_agent for marker in ("mobile", "android", "iphone", "ipad")):
        return "mobile"
    return "desktop"


def classify_activation_reason(exc: BaseException) -> str:
    """Map an exception to a bounded activation failure reason."""
    if isinstance(exc, AuthError):
        return "auth_error"
    if isinstance(exc, HostResolutionError):
        return "host_resolution_error"
    if isinstance(exc, VetmanagerError):
        return "vetmanager_error"
    if isinstance(exc, ValueError):
        return "validation_error"
    return "unknown"


async def cleanup_activation_events(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> int:
    """Delete old activation events, throttled to once per day by default."""
    current = now or _now_utc()
    if not is_activation_event_cleanup_due(now=current, force=force):
        return 0
    cutoff = current - timedelta(days=ACTIVATION_EVENT_RETENTION_DAYS)
    result = await session.execute(
        delete(ActivationEvent).where(ActivationEvent.created_at < cutoff)
    )
    return int(result.rowcount or 0)


async def record_activation_event_best_effort(
    session: AsyncSession,
    *,
    account_id: int,
    event_name: str,
    auth_mode: str | None = None,
    device_class: str | None = None,
    reason_class: str | None = None,
    copy_kind: str | None = None,
) -> None:
    """Persist an activation event without breaking the caller on failure."""
    safe_event = _coerce(event_name, ACTIVATION_EVENT_NAMES, "")
    if not safe_event:
        RUNTIME_LOGGER.warning(
            "Activation event dropped",
            extra={
                "event_name": "activation_event_dropped",
                "account_id": account_id,
                "dropped_event": event_name,
            },
        )
        return
    safe_auth_mode = _coerce(auth_mode, ACTIVATION_AUTH_MODES, "unknown")
    safe_device = _coerce(device_class, ACTIVATION_DEVICE_CLASSES, "unknown")
    safe_reason = (
        _coerce(reason_class, ACTIVATION_REASON_CLASSES, "unknown")
        if reason_class is not None
        else None
    )
    safe_copy_kind = (
        _coerce(copy_kind, ACTIVATION_COPY_KINDS, "unknown")
        if copy_kind is not None
        else None
    )
    try:
        cleanup_now = _now_utc()
        cleanup_due = is_activation_event_cleanup_due(now=cleanup_now)
        session.add(
            ActivationEvent(
                account_id=account_id,
                event_name=safe_event,
                auth_mode=safe_auth_mode,
                device_class=safe_device,
                reason_class=safe_reason,
                copy_kind=safe_copy_kind,
            )
        )
        await cleanup_activation_events(session, now=cleanup_now)
        await session.commit()
        if cleanup_due:
            mark_activation_event_cleanup_succeeded(now=cleanup_now)
    except Exception as exc:  # pragma: no cover - defensive route boundary
        await session.rollback()
        RUNTIME_LOGGER.warning(
            "Activation event persistence failed",
            extra={
                "event_name": "activation_event_persist_failed",
                "account_id": account_id,
                "activation_event": safe_event,
                "error_class": type(exc).__name__,
            },
        )

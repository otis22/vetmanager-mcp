"""Best-effort, durable observations of the first session."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from observability_logging import RUNTIME_LOGGER
from storage import get_session_factory
from storage_models import Account, AccountFirstSession, OAuthGrant, ServiceBearerToken

_LAST_FAILURE_LOG: dict[str, float] = {}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def release_cutoff() -> datetime:
    """UTC rollout boundary; set to the actual release instant before deployment."""
    value = os.environ.get("FIRST_SESSION_RELEASE_CUTOFF_UTC") or "9999-01-01T00:00:00+00:00"
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone missing")
        return result.astimezone(timezone.utc)
    except ValueError as exc:
        _failure("cutoff_config", exc)
        return datetime(9999, 1, 1, tzinfo=timezone.utc)


def _failure(operation: str, exc: Exception) -> None:
    now = time.monotonic()
    if now - _LAST_FAILURE_LOG.get(operation, -float("inf")) < 60:
        return
    _LAST_FAILURE_LOG[operation] = now
    try:
        RUNTIME_LOGGER.warning(
            "First-session telemetry failed",
            extra={"event_name": "first_session_telemetry_failed", "operation": operation,
                   "error_class": type(exc).__name__},
        )
    except Exception:
        pass


async def lock_account_and_check_first_credential(session: AsyncSession, account_id: int) -> bool:
    """Serialize both issuance channels before looking for any earlier credentials."""
    account = await session.scalar(select(Account).where(Account.id == account_id).with_for_update())
    if account is None:
        return False
    if _utc(account.created_at) < release_cutoff():
        return False
    prior = await session.scalar(select(
        exists(select(ServiceBearerToken.id).where(ServiceBearerToken.account_id == account_id))
    ))
    if prior:
        return False
    return not bool(await session.scalar(select(
        exists(select(OAuthGrant.id).where(OAuthGrant.account_id == account_id))
    )))


async def anchor_first_credential(session: AsyncSession, account_id: int, eligible: bool) -> None:
    if not eligible:
        return
    try:
        async with session.begin_nested():
            session.add(AccountFirstSession(
                account_id=account_id, first_token_issued_at=datetime.now(timezone.utc),
            ))
            await session.flush()
    except Exception as exc:
        _failure("anchor", exc)


async def observe_first_action(account_id: int | None, field: str) -> None:
    if account_id is None or field not in {"first_tool_success_at", "first_report_saved_at"}:
        return
    try:
        async with get_session_factory()() as session:
            await session.execute(
                update(AccountFirstSession)
                .where(AccountFirstSession.account_id == account_id)
                .where(getattr(AccountFirstSession, field).is_(None))
                .values({field: datetime.now(timezone.utc)})
            )
            await session.commit()
    except Exception as exc:
        _failure(field, exc)

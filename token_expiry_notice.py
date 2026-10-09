"""Best-effort, per-bearer expiry notice claim at the MCP response boundary."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Callable, TypeVar

from sqlalchemy import exists, select, text, update

from auth.bearer import _token_usage_stat_conflict_insert_statement
from storage import get_session_factory
from storage_models import ServiceBearerToken, TOKEN_STATUS_ACTIVE, TokenUsageStat

_NOTICE_SUBJECT: ContextVar[tuple[int, int] | None] = ContextVar("expiry_notice_subject", default=None)
T = TypeVar("T")


def open_notice_subject():
    return _NOTICE_SUBJECT.set(None)


def reset_notice_subject(token) -> None:
    _NOTICE_SUBJECT.reset(token)


def set_notice_subject(account_id: int | None, bearer_token_id: int | None) -> None:
    _NOTICE_SUBJECT.set((account_id, bearer_token_id) if account_id is not None and bearer_token_id is not None else None)


def get_notice_subject() -> tuple[int, int] | None:
    return _NOTICE_SUBJECT.get()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def expiry_notice_text(days: int) -> str:
    if days % 10 == 1 and days % 100 != 11:
        suffix = "день"
    elif days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        suffix = "дня"
    else:
        suffix = "дней"
    return (
        f"Токен истекает через {days} {suffix}. Сообщите человеку: выпустите новый токен "
        "в кабинете с теми же правами, настройкой очистки данных и IP-ограничением, "
        "затем замените им старый в подключении."
    )


async def claim_expiry_notice(
    account_id: int, bearer_token_id: int, *, now: datetime | None = None,
    prepare: Callable[[int], T] | None = None,
    session_factory=None,
) -> T | int | None:
    """Return prepared notice only for the winning transaction; deadline includes pool and commit."""
    current = _utc(now or datetime.now(timezone.utc))
    factory = session_factory or get_session_factory()
    async with asyncio.timeout(0.5):
        async with factory() as session:
            async with session.begin():
                if session.get_bind().dialect.name == "postgresql":
                    await session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                    await session.execute(text("SET LOCAL statement_timeout = '400ms'"))
                token = await session.scalar(
                    select(ServiceBearerToken)
                    .where(ServiceBearerToken.id == bearer_token_id,
                           ServiceBearerToken.account_id == account_id,
                           ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
                    .with_for_update()
                )
                if token is None or token.expires_at is None:
                    return None
                remaining = (_utc(token.expires_at) - current).total_seconds()
                days = ceil(remaining / 86400)
                if not 1 <= days <= 14:
                    return None
                candidate = prepare(days) if prepare else days
                await session.execute(_token_usage_stat_conflict_insert_statement(
                    session.get_bind().dialect.name, bearer_token_id,
                ))
                valid_token = exists(select(ServiceBearerToken.id).where(
                    ServiceBearerToken.id == bearer_token_id,
                    ServiceBearerToken.account_id == account_id,
                    ServiceBearerToken.status == TOKEN_STATUS_ACTIVE,
                    ServiceBearerToken.expires_at.is_not(None),
                    ServiceBearerToken.expires_at > current,
                ))
                claimed = await session.execute(
                    update(TokenUsageStat)
                    .where(TokenUsageStat.bearer_token_id == bearer_token_id,
                           (TokenUsageStat.expiry_notice_at.is_(None) |
                            (TokenUsageStat.expiry_notice_at <= current - timedelta(hours=24))),
                           valid_token)
                    .values(expiry_notice_at=current)
                    .returning(TokenUsageStat.id)
                )
                if claimed.scalar_one_or_none() is None:
                    return None
            return candidate

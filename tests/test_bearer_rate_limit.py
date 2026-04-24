"""Unit tests for stage 27.1 bearer-token rate limiting."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

import bearer_rate_limiter
import rate_limit_backend
from bearer_auth import resolve_bearer_auth_context
from bearer_token_manager import generate_bearer_token
from exceptions import RateLimitError
from storage_models import Account, ServiceBearerToken, TokenUsageStat, VetmanagerConnection


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "bearer-rate-limit.db")


async def _create_token(
    session_factory,
    *,
    email: str,
    domain: str,
) -> str:
    raw_token = generate_bearer_token()
    async with session_factory() as session:
        account = Account(email=email, status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain=domain,
        )
        connection.set_credentials(
            {"domain": domain, "api_key": f"{domain}-secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name=f"{domain} token")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()
    return raw_token


@pytest.mark.asyncio
async def test_bearer_rate_limit_blocks_request_above_limit(session_factory, monkeypatch):
    """Third request in the same window should fail with a 429-safe error."""
    raw_token = await _create_token(
        session_factory,
        email="ops@example.com",
        domain="clinic-a",
    )
    monkeypatch.setenv("BEARER_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("BEARER_RATE_LIMIT_WINDOW_SECONDS", "60")
    bearer_rate_limiter.reset_bearer_rate_limiter()
    start = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)

    try:
        async with session_factory() as session:
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=start,
            )
        async with session_factory() as session:
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=start + timedelta(seconds=10),
            )
        async with session_factory() as session:
            with pytest.raises(RateLimitError, match="rate limit exceeded") as exc_info:
                await resolve_bearer_auth_context(
                    raw_token,
                    session,
                    encryption_key=TEST_ENCRYPTION_KEY,
                    now=start + timedelta(seconds=20),
                )

        async with session_factory() as session:
            stats = await session.scalar(
                select(TokenUsageStat).where(TokenUsageStat.bearer_token_id == 1)
            )
    finally:
        bearer_rate_limiter.reset_bearer_rate_limiter()

    assert exc_info.value.status_code == 429
    assert exc_info.value.retry_after_seconds == 60
    assert stats is not None
    assert stats.request_count == 2


@pytest.mark.asyncio
async def test_bearer_rate_limit_isolated_per_token(session_factory, monkeypatch):
    """One noisy token must not consume the budget of another token."""
    first_token = await _create_token(
        session_factory,
        email="first@example.com",
        domain="clinic-first",
    )
    second_token = await _create_token(
        session_factory,
        email="second@example.com",
        domain="clinic-second",
    )
    monkeypatch.setenv("BEARER_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("BEARER_RATE_LIMIT_WINDOW_SECONDS", "60")
    bearer_rate_limiter.reset_bearer_rate_limiter()
    start = datetime(2026, 3, 21, 12, 30, tzinfo=timezone.utc)

    try:
        async with session_factory() as session:
            await resolve_bearer_auth_context(
                first_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=start,
            )
        async with session_factory() as session:
            with pytest.raises(RateLimitError):
                await resolve_bearer_auth_context(
                    first_token,
                    session,
                    encryption_key=TEST_ENCRYPTION_KEY,
                    now=start + timedelta(seconds=5),
                )
        async with session_factory() as session:
            context = await resolve_bearer_auth_context(
                second_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=start + timedelta(seconds=5),
            )
    finally:
        bearer_rate_limiter.reset_bearer_rate_limiter()

    assert context.account_id == 2
    assert context.domain == "clinic-second"


@pytest.mark.asyncio
async def test_bearer_rate_limit_allows_requests_after_window_expires(session_factory, monkeypatch):
    """Requests should be admitted again once the sliding window has moved on."""
    raw_token = await _create_token(
        session_factory,
        email="ops@example.com",
        domain="clinic-window",
    )
    monkeypatch.setenv("BEARER_RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("BEARER_RATE_LIMIT_WINDOW_SECONDS", "60")
    start = datetime(2026, 3, 21, 13, 0, tzinfo=timezone.utc)
    current_time = start

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return current_time

    monkeypatch.setattr(rate_limit_backend, "datetime", _FrozenDatetime)
    bearer_rate_limiter.reset_bearer_rate_limiter()

    try:
        async with session_factory() as session:
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=start,
            )
        current_time = start + timedelta(seconds=30)
        async with session_factory() as session:
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=start + timedelta(seconds=30),
            )
        current_time = start + timedelta(seconds=61)
        async with session_factory() as session:
            context = await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=start + timedelta(seconds=60),
            )
    finally:
        bearer_rate_limiter.reset_bearer_rate_limiter()

    assert context.domain == "clinic-window"


@pytest.mark.asyncio
async def test_bearer_rate_limit_uses_shared_backend_namespace(monkeypatch):
    """Bearer limiter must use shared backend with token id, never the raw token."""
    calls: list[tuple[str, str, int, int]] = []

    class _FakeBackend:
        async def consume_hit(self, namespace, key, *, limit, window_seconds):
            calls.append((namespace, key, limit, window_seconds))
            return 1, True

    async def _fake_get_rate_limit_backend():
        return _FakeBackend()

    monkeypatch.setenv("BEARER_RATE_LIMIT_REQUESTS", "7")
    monkeypatch.setenv("BEARER_RATE_LIMIT_WINDOW_SECONDS", "13")
    monkeypatch.setattr(
        "auth.rate_limit.get_rate_limit_backend",
        _fake_get_rate_limit_backend,
    )
    bearer_rate_limiter.reset_bearer_rate_limiter()

    await bearer_rate_limiter.BEARER_RATE_LIMITER.check_or_raise(123)

    assert calls == [("bearer", "123", 7, 13)]

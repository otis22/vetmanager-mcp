"""Process-local sliding-window rate limiter for bearer-authenticated requests."""

from __future__ import annotations

import asyncio
import math
import os
from collections import deque
from datetime import datetime, timezone
from weakref import WeakKeyDictionary

from exceptions import RateLimitError

DEFAULT_BEARER_RATE_LIMIT_REQUESTS = 1000
DEFAULT_BEARER_RATE_LIMIT_WINDOW_SECONDS = 60


def _env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def get_bearer_rate_limit_requests() -> int:
    """Return max admitted requests per sliding window for one bearer token."""
    return _env_int("BEARER_RATE_LIMIT_REQUESTS", DEFAULT_BEARER_RATE_LIMIT_REQUESTS)


def get_bearer_rate_limit_window_seconds() -> int:
    """Return sliding-window length in seconds for bearer-token rate limiting."""
    return _env_int(
        "BEARER_RATE_LIMIT_WINDOW_SECONDS",
        DEFAULT_BEARER_RATE_LIMIT_WINDOW_SECONDS,
    )


class InMemoryBearerRateLimiter:
    """Track recent request timestamps per bearer token within one process."""

    def __init__(self) -> None:
        self._requests_by_token: dict[int, deque[float]] = {}
        self._locks_by_loop: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
            WeakKeyDictionary()
        )

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._locks_by_loop.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            self._locks_by_loop[loop] = lock
        return lock

    async def check_or_raise(
        self,
        bearer_token_id: int,
        *,
        now: datetime | None = None,
    ) -> None:
        """Reserve one request slot or raise a 429-safe error."""
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current_ts = current.timestamp()
        request_limit = get_bearer_rate_limit_requests()
        window_seconds = get_bearer_rate_limit_window_seconds()
        cutoff = current_ts - window_seconds

        async with self._get_lock():
            bucket = self._requests_by_token.setdefault(bearer_token_id, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= request_limit:
                retry_after_seconds = max(
                    1,
                    math.ceil(bucket[0] + window_seconds - current_ts),
                )
                raise RateLimitError(
                    "Bearer token rate limit exceeded. Retry later.",
                    retry_after_seconds=retry_after_seconds,
                )

            bucket.append(current_ts)

    async def reset(self) -> None:
        """Clear process-local limiter state, mainly for tests."""
        async with self._get_lock():
            self._requests_by_token.clear()


BEARER_RATE_LIMITER = InMemoryBearerRateLimiter()


def reset_bearer_rate_limiter() -> None:
    """Synchronously replace limiter state for isolated tests."""
    global BEARER_RATE_LIMITER
    BEARER_RATE_LIMITER = InMemoryBearerRateLimiter()

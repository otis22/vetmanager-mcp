"""Process-local sliding-window rate limiter for bearer-authenticated requests.

Stage 103a: extracted from `bearer_rate_limiter.py`. Kept as a focused
submodule; consolidation with the generic `rate_limit_backend` namespace
is tracked separately — substantial enough to warrant its own stage.
"""

from __future__ import annotations

import asyncio
import math
import os
from collections import deque
from datetime import datetime, timezone
from weakref import WeakKeyDictionary

from exceptions import RateLimitError
from observability_logging import RUNTIME_LOGGER

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
                # Stage 107.1 (H10 fix): log at raise site so throttling
                # leaves a searchable event even if the caller's metric path
                # changes. Token id only — не логируем raw token.
                RUNTIME_LOGGER.warning(
                    "Bearer rate limit triggered",
                    extra={
                        "event_name": "bearer_rate_limit_triggered",
                        "token_id": bearer_token_id,
                        "retry_after_seconds": retry_after_seconds,
                        "request_limit": request_limit,
                        "window_seconds": window_seconds,
                    },
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
    """Synchronously replace limiter state for isolated tests.

    Rebinds BOTH the canonical `auth.rate_limit.BEARER_RATE_LIMITER`
    name and the top-level `bearer_rate_limiter.BEARER_RATE_LIMITER`
    shim attribute so tests that `import bearer_rate_limiter` and read
    `bearer_rate_limiter.BEARER_RATE_LIMITER` see the fresh instance.
    """
    global BEARER_RATE_LIMITER
    fresh = InMemoryBearerRateLimiter()
    BEARER_RATE_LIMITER = fresh
    # Keep the shim's module-level name in sync for any legacy caller
    # that still reads it by attribute (import-time snapshots would
    # otherwise go stale after reset).
    try:
        import sys
        shim = sys.modules.get("bearer_rate_limiter")
        if shim is not None:
            shim.BEARER_RATE_LIMITER = fresh
    except Exception:
        pass

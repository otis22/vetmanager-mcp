"""Bearer-authenticated request rate limiting via the shared backend."""

from __future__ import annotations

import sys

from env_utils import env_int
from exceptions import RateLimitError
from observability_logging import RUNTIME_LOGGER
from rate_limit_backend import get_rate_limit_backend, reset_rate_limit_backend

DEFAULT_BEARER_RATE_LIMIT_REQUESTS = 1000
DEFAULT_BEARER_RATE_LIMIT_WINDOW_SECONDS = 60


def get_bearer_rate_limit_requests() -> int:
    """Return max admitted requests per sliding window for one bearer token."""
    return env_int("BEARER_RATE_LIMIT_REQUESTS", DEFAULT_BEARER_RATE_LIMIT_REQUESTS)


def get_bearer_rate_limit_window_seconds() -> int:
    """Return sliding-window length in seconds for bearer-token rate limiting."""
    return env_int(
        "BEARER_RATE_LIMIT_WINDOW_SECONDS",
        DEFAULT_BEARER_RATE_LIMIT_WINDOW_SECONDS,
    )


class InMemoryBearerRateLimiter:
    """Compatibility adapter backed by the shared rate-limit backend."""

    async def check_or_raise(self, bearer_token_id: int) -> None:
        """Reserve one request slot or raise a 429-safe error."""
        request_limit = get_bearer_rate_limit_requests()
        window_seconds = get_bearer_rate_limit_window_seconds()

        backend = await get_rate_limit_backend()
        _, allowed = await backend.consume_hit(
            "bearer",
            str(bearer_token_id),
            limit=request_limit,
            window_seconds=window_seconds,
        )

        if not allowed:
            retry_after_seconds = max(1, window_seconds)
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

    async def reset(self) -> None:
        """Clear shared limiter state, mainly for tests."""
        backend = await get_rate_limit_backend()
        await backend.reset_all()


BEARER_RATE_LIMITER = InMemoryBearerRateLimiter()


def reset_bearer_rate_limiter() -> None:
    """Synchronously replace limiter state for isolated tests.

    Rebinds BOTH the canonical `auth.rate_limit.BEARER_RATE_LIMITER`
    name and the top-level `bearer_rate_limiter.BEARER_RATE_LIMITER`
    shim attribute so tests that `import bearer_rate_limiter` and read
    `bearer_rate_limiter.BEARER_RATE_LIMITER` see the fresh instance.
    """
    global BEARER_RATE_LIMITER
    reset_rate_limit_backend()
    fresh = InMemoryBearerRateLimiter()
    BEARER_RATE_LIMITER = fresh
    # Keep the shim's module-level name in sync for any legacy caller
    # that still reads it by attribute (import-time snapshots would
    # otherwise go stale after reset).
    try:
        shim = sys.modules.get("bearer_rate_limiter")
        if shim is not None:
            shim.BEARER_RATE_LIMITER = fresh
    except Exception:
        pass

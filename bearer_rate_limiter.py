"""Backward-compat shim — canonical location is `auth.rate_limit`.

Stage 103a: the bearer-token rate limiter lives under `auth.rate_limit`.
This shim re-exports the limiter instance + helpers so existing
`import bearer_rate_limiter` + `bearer_rate_limiter.BEARER_RATE_LIMITER`
/ `bearer_rate_limiter.reset_bearer_rate_limiter()` callers keep
working unchanged.

Note: `BEARER_RATE_LIMITER` here is a MODULE-LEVEL rebind of the
canonical instance. Tests that call `reset_bearer_rate_limiter()` MUST
use the canonical function (which rebinds both names) to avoid drift.
"""

from auth.rate_limit import (  # noqa: F401
    BEARER_RATE_LIMITER,
    DEFAULT_BEARER_RATE_LIMIT_REQUESTS,
    DEFAULT_BEARER_RATE_LIMIT_WINDOW_SECONDS,
    InMemoryBearerRateLimiter,
    get_bearer_rate_limit_requests,
    get_bearer_rate_limit_window_seconds,
    reset_bearer_rate_limiter,
)

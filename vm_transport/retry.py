"""Retry policy: backoff math, Retry-After parsing, retry constants.

Stage 103d: extracted from `vetmanager_client.py`. Pure functions — no
state, no I/O. Constants are module-level and read at client construction
time; override them with `monkeypatch.setattr(vetmanager_client, ...)`
(re-exported from there for BC).
"""

from __future__ import annotations

import datetime as _dt
import email.utils
import math
import random

# Retries for idempotent reads (GET). POST/PUT/DELETE do not retry on 5xx/429
# to preserve idempotency (VM API has no idempotency keys).
MAX_RETRIES_READ = 3
MAX_RETRIES_WRITE = 0

# Statuses worth retrying for GET. 401/403/404/400 are not transient.
RETRY_STATUS_CODES = frozenset({429, 502, 503, 504})

BACKOFF_BASE_SECONDS = 0.2
BACKOFF_MAX_SECONDS = 5.0

# Hard cap on Retry-After to prevent DoS via `Retry-After: 1e9`.
RETRY_AFTER_MAX_SECONDS = 300.0


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse an HTTP `Retry-After` header value into seconds.

    Supports both integer-seconds and HTTP-date forms (RFC 7231).
    Rejects non-finite (inf/nan) values. Clamps to `RETRY_AFTER_MAX_SECONDS`
    to avoid pathological upstream responses blocking the caller forever.

    Returns None if the header is missing or unparseable.
    """
    if not header_value:
        return None
    header_value = header_value.strip()
    try:
        seconds = float(header_value)
        if not math.isfinite(seconds):
            return None
        return max(0.0, min(seconds, RETRY_AFTER_MAX_SECONDS))
    except ValueError:
        pass
    try:
        parsed_dt = email.utils.parsedate_to_datetime(header_value)
        if parsed_dt is None:
            return None
        now = _dt.datetime.now(tz=parsed_dt.tzinfo or _dt.timezone.utc)
        delta = (parsed_dt - now).total_seconds()
        if not math.isfinite(delta):
            return None
        return max(0.0, min(delta, RETRY_AFTER_MAX_SECONDS))
    except Exception:
        return None


def backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """Compute backoff delay in seconds.

    `attempt` starts at 0 for the first retry. Uses exponential backoff
    (base 0.2s, doubled each attempt, capped at 5s) plus up to 100ms jitter
    to de-sync concurrent callers hitting the same upstream.

    If `retry_after` is provided, the returned delay is at least
    `retry_after` — we honour the upstream hint but never wait less than
    our computed backoff.
    """
    computed = min(
        BACKOFF_BASE_SECONDS * (2 ** attempt) + random.uniform(0, 0.1),
        BACKOFF_MAX_SECONDS,
    )
    if retry_after is not None:
        return max(computed, retry_after)
    return computed

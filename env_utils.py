"""Environment variable helpers with type coercion and positive-only guards.

Stage 108.10: consolidates three near-identical copies of `_env_int` /
`_env_float` that lived in `auth/rate_limit.py`, `vm_transport/breaker.py`,
and (historically) `rate_limit_backend.py`. A small seam here gives future
config-validation work one place to hook into.
"""

from __future__ import annotations

import math
import os


def env_int(name: str, default: int, *, positive_only: bool = True) -> int:
    """Read env var `name` as int; fall back to `default` on missing/malformed.

    If `positive_only=True` (default), values <= 0 also fall back to default —
    most auth / breaker thresholds make no sense at zero or negative.
    """
    raw = os.environ.get(name, "").strip() if os.environ.get(name) is not None else ""
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if positive_only and value <= 0:
        return default
    return value


def env_float(name: str, default: float, *, positive_only: bool = True) -> float:
    """Read env var `name` as float; fall back to `default` on missing/malformed.

    Also rejects non-finite (inf/nan). If `positive_only=True` (default),
    values <= 0 fall back too.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value):
        return default
    if positive_only and value <= 0:
        return default
    return value

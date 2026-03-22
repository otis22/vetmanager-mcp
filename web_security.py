"""Security helpers for the public web UI."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import os
from secrets import token_bytes

from starlette.requests import Request
from starlette.responses import Response

from exceptions import RateLimitError
from web_auth import get_web_session_cookie_settings, get_web_session_secret

CSRF_COOKIE_NAME = "vm_csrf"
CSRF_FIELD_NAME = "csrf_token"
CSRF_MAX_AGE_SECONDS = 60 * 60 * 2

_RATE_LIMIT_STATE: dict[str, dict[str, deque[float]]] = defaultdict(lambda: defaultdict(deque))


def _sign_payload(payload: str, *, secret: str | None = None) -> str:
    key = (secret or get_web_session_secret()).encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_csrf_token(
    *,
    now: datetime | None = None,
    secret: str | None = None,
) -> str:
    """Create signed CSRF token suitable for double-submit cookie validation."""
    current = now or datetime.now(timezone.utc)
    issued_at = int(current.timestamp())
    nonce = base64.urlsafe_b64encode(token_bytes(16)).decode("ascii").rstrip("=")
    payload = f"{nonce}.{issued_at}"
    signature = _sign_payload(payload, secret=secret)
    return f"{payload}.{signature}"


def read_csrf_token(
    raw_token: str | None,
    *,
    now: datetime | None = None,
    secret: str | None = None,
) -> str | None:
    """Validate signed CSRF token and return it when valid."""
    if not raw_token:
        return None
    try:
        nonce, issued_at_raw, signature = raw_token.split(".", 2)
        payload = f"{nonce}.{issued_at_raw}"
        expected = _sign_payload(payload, secret=secret)
        if not hmac.compare_digest(signature, expected):
            return None
        issued_at = datetime.fromtimestamp(int(issued_at_raw), tz=timezone.utc)
    except (TypeError, ValueError):
        return None

    current = now or datetime.now(timezone.utc)
    if current - issued_at > timedelta(seconds=CSRF_MAX_AGE_SECONDS):
        return None
    return raw_token


def ensure_csrf_cookie(
    response: Response,
    *,
    existing_token: str | None = None,
) -> str:
    """Ensure response carries a valid CSRF cookie and return the active token."""
    secure, samesite = get_web_session_cookie_settings()
    token = read_csrf_token(existing_token) or create_csrf_token()
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=CSRF_MAX_AGE_SECONDS,
        httponly=False,
        samesite=samesite,
        secure=secure,
        path="/",
    )
    return token


def validate_csrf_request(request: Request, submitted_token: str | None) -> None:
    """Raise ValueError when CSRF cookie and submitted token are missing or invalid."""
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    valid_cookie = read_csrf_token(cookie_token)
    valid_submitted = read_csrf_token(submitted_token)
    if not valid_cookie or not valid_submitted or not hmac.compare_digest(valid_cookie, valid_submitted):
        raise ValueError("Invalid CSRF token.")


def _trusted_proxy_hosts() -> set[str]:
    raw_value = os.environ.get("WEB_TRUSTED_PROXY_IPS", "")
    return {
        candidate.strip()
        for candidate in raw_value.split(",")
        if candidate.strip()
    }


def resolve_client_ip(
    *,
    client_host: str | None,
    forwarded_for: str | None = None,
) -> str:
    """Resolve client IP, trusting forwarded headers only behind configured proxies."""
    direct_host = (client_host or "").strip() or "unknown"
    trusted_proxies = _trusted_proxy_hosts()
    if direct_host in trusted_proxies:
        forwarded_chain = (forwarded_for or "").strip()
        if forwarded_chain:
            forwarded_ip = forwarded_chain.split(",", 1)[0].strip()
            if forwarded_ip:
                return forwarded_ip
    return direct_host


def get_request_ip(request: Request) -> str:
    """Return best-effort client IP for process-local safety controls."""
    return resolve_client_ip(
        client_host=getattr(request.client, "host", None),
        forwarded_for=request.headers.get("x-forwarded-for"),
    )


def _prune_entries(entries: deque[float], *, now_ts: float, window_seconds: int) -> None:
    lower_bound = now_ts - window_seconds
    while entries and entries[0] <= lower_bound:
        entries.popleft()


def check_rate_limit(namespace: str, key: str, *, limit: int, window_seconds: int) -> None:
    """Raise 429 when the key already reached the configured number of hits."""
    if limit <= 0:
        return
    now_ts = datetime.now(timezone.utc).timestamp()
    entries = _RATE_LIMIT_STATE[namespace][key]
    _prune_entries(entries, now_ts=now_ts, window_seconds=window_seconds)
    if len(entries) >= limit:
        raise RateLimitError(
            "Too many requests.",
            retry_after_seconds=window_seconds,
        )


def record_rate_limit_hit(namespace: str, key: str, *, window_seconds: int) -> None:
    """Append one hit for the given namespace/key pair."""
    now_ts = datetime.now(timezone.utc).timestamp()
    entries = _RATE_LIMIT_STATE[namespace][key]
    _prune_entries(entries, now_ts=now_ts, window_seconds=window_seconds)
    entries.append(now_ts)


def clear_rate_limit_key(namespace: str, key: str) -> None:
    """Clear limiter state for a key after successful auth."""
    _RATE_LIMIT_STATE[namespace].pop(key, None)


def get_rate_limit_config(prefix: str, *, default_attempts: int, default_window_seconds: int) -> tuple[int, int]:
    """Resolve web limiter settings from env with stable defaults."""
    attempts = int(os.environ.get(f"{prefix}_ATTEMPTS", str(default_attempts)).strip())
    window_seconds = int(os.environ.get(f"{prefix}_WINDOW_SECONDS", str(default_window_seconds)).strip())
    return attempts, window_seconds


def reset_web_security_state() -> None:
    """Clear process-local limiter state for tests."""
    _RATE_LIMIT_STATE.clear()

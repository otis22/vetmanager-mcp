"""Account registration, login, and signed web session helpers."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta, timezone
from secrets import token_bytes, token_urlsafe

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from storage_models import ACCOUNT_STATUS_ACTIVE, Account

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 390_000
SESSION_COOKIE_NAME = "vm_account_session"
SESSION_MAX_AGE_SECONDS = int(
    os.environ.get("WEB_SESSION_MAX_AGE_SECONDS", 60 * 60 * 24)
)  # default: 24 hours


PASSWORD_MIN_LENGTH = 10


def _validate_password_strength(password: str) -> None:
    """Validate password meets minimum complexity requirements."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Пароль должен быть не менее {PASSWORD_MIN_LENGTH} символов."
        )
    import re

    if not re.search(r"[A-ZА-ЯЁ]", password):
        raise ValueError("Пароль должен содержать хотя бы одну заглавную букву.")
    if not re.search(r"[a-zа-яё]", password):
        raise ValueError("Пароль должен содержать хотя бы одну строчную букву.")
    if not re.search(r"\d", password):
        raise ValueError("Пароль должен содержать хотя бы одну цифру.")


def normalize_account_email(email: str) -> str:
    """Return normalized account email used for unique lookup."""
    return email.strip().lower()


def hash_account_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with per-password salt."""
    salt = token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return (
        f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(digest).decode('ascii')}"
    )


def verify_account_password(password: str, password_hash: str | None) -> bool:
    """Verify plaintext password against stored PBKDF2 digest.

    Always performs a full PBKDF2 computation to prevent timing-based
    account enumeration (constant-time regardless of hash validity).
    """
    dummy_salt = b"\x00" * 16
    valid = True
    iterations = PASSWORD_ITERATIONS
    salt = dummy_salt
    expected = b""

    if not password_hash:
        valid = False
    else:
        try:
            scheme, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
            if scheme != PASSWORD_SCHEME:
                valid = False
            else:
                iterations = int(iterations_raw)
                salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
                expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
        except (ValueError, TypeError):
            valid = False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return valid and hmac.compare_digest(actual, expected)


def get_web_session_secret() -> str:
    """Return dedicated session-signing secret for web auth surfaces."""
    secret = os.environ.get("WEB_SESSION_SECRET")
    if not secret:
        raise RuntimeError("Missing WEB_SESSION_SECRET for signed web sessions.")
    return secret


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_web_session_cookie_settings() -> tuple[bool, str]:
    """Return hardened default cookie settings with explicit env overrides."""
    secure = _env_flag("WEB_SESSION_SECURE", True)
    samesite = (os.environ.get("WEB_SESSION_SAMESITE") or "strict").strip().lower() or "strict"
    if samesite not in {"strict", "lax", "none"}:
        samesite = "strict"
    return secure, samesite


def _session_signature(payload: str, *, secret: str | None = None) -> str:
    key = (secret or get_web_session_secret()).encode("utf-8")
    return hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def create_account_session_token(
    account_id: int,
    *,
    now: datetime | None = None,
    secret: str | None = None,
) -> str:
    """Create signed cookie payload storing account id, issue time, and nonce."""
    current = now or datetime.now(timezone.utc)
    issued_at = int(current.timestamp())
    nonce = token_urlsafe(8)
    payload = f"{account_id}.{issued_at}.{nonce}"
    signature = _session_signature(payload, secret=secret)
    return f"{payload}.{signature}"


def read_account_session_token(
    raw_token: str | None,
    *,
    now: datetime | None = None,
    secret: str | None = None,
) -> int | None:
    """Validate signed session token and return account id if valid.

    Supports both legacy 3-part (id.ts.sig) and current 4-part (id.ts.nonce.sig) tokens.
    """
    if not raw_token:
        return None
    try:
        parts = raw_token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        payload, signature = parts
        expected = _session_signature(payload, secret=secret)
        if not hmac.compare_digest(signature, expected):
            return None
        payload_parts = payload.split(".")
        if len(payload_parts) < 2:
            return None
        account_id_raw = payload_parts[0]
        issued_at_raw = payload_parts[1]
        issued_at = datetime.fromtimestamp(int(issued_at_raw), tz=timezone.utc)
    except (TypeError, ValueError):
        return None

    current = now or datetime.now(timezone.utc)
    if current - issued_at > timedelta(seconds=SESSION_MAX_AGE_SECONDS):
        return None

    try:
        return int(account_id_raw)
    except ValueError:
        return None


def set_account_session_cookie(response: Response, account_id: int) -> None:
    """Attach signed web session cookie to response."""
    secure, samesite = get_web_session_cookie_settings()
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_account_session_token(account_id),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path="/",
    )


def clear_account_session_cookie(response: Response) -> None:
    """Delete signed session cookie from response."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


async def register_account(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> Account:
    """Create a new active account with password hash."""
    normalized_email = normalize_account_email(email)
    if not normalized_email or not EMAIL_RE.match(normalized_email):
        raise ValueError("Provide a valid email address.")
    _validate_password_strength(password)

    existing = await session.scalar(select(Account).where(Account.email == normalized_email))
    if existing is not None:
        raise ValueError("Account with this email already exists.")

    # PBKDF2 with 390k iterations takes ~80-150ms of pure CPU. Offload to
    # the default thread pool so the event loop stays responsive to other
    # requests during account creation bursts.
    password_hash = await asyncio.to_thread(hash_account_password, password)
    account = Account(
        email=normalized_email,
        password_hash=password_hash,
        status=ACCOUNT_STATUS_ACTIVE,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def authenticate_account(
    session: AsyncSession,
    *,
    email: str,
    password: str,
) -> Account | None:
    """Return active account for valid credentials, otherwise None."""
    normalized_email = normalize_account_email(email)
    account = await session.scalar(select(Account).where(Account.email == normalized_email))
    if account is None or account.status != ACCOUNT_STATUS_ACTIVE:
        return None
    # Offload PBKDF2 from the event loop for the same reason as creation.
    password_valid = await asyncio.to_thread(
        verify_account_password, password, account.password_hash
    )
    if not password_valid:
        return None
    return account

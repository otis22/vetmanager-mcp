"""Single-use, short-lived confirmations for a pet status preview."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from functools import lru_cache

import redis

from exceptions import ToolInputError
from runtime_auth import get_current_runtime_credentials

TTL = 600
_LOCK = threading.Lock()
_LOCAL: dict[str, tuple[str, float]] = {}


def _identity() -> dict:
    credentials = get_current_runtime_credentials()
    if credentials is None:
        raise ToolInputError("No active connection for pet status confirmation.")
    return {"account": credentials.account_id, "connection": credentials.connection_id,
            "bearer_token": credentials.bearer_token_id,
            "subject_type": credentials.auth_subject_type,
            "subject_id": credentials.auth_subject_id,
            "domain": credentials.domain}


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _context_digest(context: dict) -> str:
    credentials = get_current_runtime_credentials()
    if credentials is None or not credentials.vetmanager_auth.credential:
        raise ToolInputError("No active connection for pet status confirmation.")
    raw = json.dumps({"identity": _identity(), "context": context},
                     sort_keys=True, default=str, separators=(",", ":")).encode()
    key = hmac.new(credentials.vetmanager_auth.credential.encode(),
                   b"pet-status-confirm-v1", hashlib.sha256).digest()
    return hmac.new(key, raw, hashlib.sha256).hexdigest()


def _redis():
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        if os.environ.get("MCP_WORKER_SLOTS", "1") != "1":
            raise ToolInputError("Shared confirmation store is unavailable.")
        return None
    return _redis_client(url, os.getpid())


@lru_cache(maxsize=2)
def _redis_client(url: str, pid: int):
    return redis.Redis.from_url(url, decode_responses=True,
                               socket_connect_timeout=1, socket_timeout=1)


def issue(context: dict) -> str:
    token = secrets.token_urlsafe(32)
    key = "vm:pet-status-confirm:" + _digest(token)
    value = _context_digest(context)
    try:
        backend = _redis()
        if backend is not None:
            if not backend.set(key, value, nx=True, ex=TTL):
                raise ToolInputError("Could not issue confirmation; preview again.")
        else:
            with _LOCK:
                now = time.monotonic()
                for old_key, (_, expiry) in list(_LOCAL.items()):
                    if expiry <= now:
                        _LOCAL.pop(old_key, None)
                if len(_LOCAL) >= 4096:
                    raise ToolInputError("Too many pending confirmations; try again later.")
                _LOCAL[key] = (value, now + TTL)
    except ToolInputError:
        raise
    except Exception as exc:
        raise ToolInputError("Confirmation store unavailable; preview again.") from exc
    return token


def consume(token: str, context: dict) -> None:
    if not isinstance(token, str) or len(token) > 128 or len(token) < 32:
        raise ToolInputError("Invalid confirmation; preview again.")
    key = "vm:pet-status-confirm:" + _digest(token)
    expected = _context_digest(context)
    try:
        backend = _redis()
        if backend is not None:
            value = backend.getdel(key)
        else:
            with _LOCK:
                item = _LOCAL.pop(key, None)
                value = item[0] if item and item[1] > time.monotonic() else None
    except ToolInputError:
        raise
    except Exception as exc:
        raise ToolInputError("Confirmation store unavailable; preview again.") from exc
    if not value or not secrets.compare_digest(value, expected):
        raise ToolInputError("Confirmation expired, reused or changed; preview again.")

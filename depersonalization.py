"""Centralized bearer-token response depersonalization helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


REDACTED_PHONE = "[redacted-phone]"
REDACTED_EMAIL = "[redacted-email]"
REDACTED_NAME = "[redacted-name]"
REDACTED_ADDRESS = "[redacted-address]"

_NAME_KEYS = frozenset({
    "name",
    "firstname",
    "lastname",
    "middlename",
    "fio",
    "clientname",
    "ownername",
    "client",
    "owner",
})
_PHONE_KEYS = frozenset({
    "phone",
    "cellphone",
    "homephone",
    "workphone",
    "ownerphone",
})
_EMAIL_KEYS = frozenset({"email"})
_ADDRESS_KEYS = frozenset({"address"})
_FREE_TEXT_KEYS = frozenset({
    "description",
    "diagnos",
    "diagnosis",
    "diagnostext",
    "diagnostypetext",
    "recomendation",
    "recommendation",
    "treatment",
    "comment",
    "note",
    "notes",
    "deathnote",
})

_EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\[redacted-phone\])(?:\+?\d[\d\-\s().]{8,}\d)")
_OWNER_PHRASE_RE = re.compile(
    r"(?u)\b(?i:(?:владелец|хозяин|owner))\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё.\-]+(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё.\-]+){0,2}"
)
_INITIALS_RE = re.compile(
    r"(?u)\b[A-ZА-ЯЁ][a-zа-яё]{1,30}\s+[A-ZА-ЯЁ]\.[A-ZА-ЯЁ]\."
)
def _normalize_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def _redaction_for_key(key: str) -> str | None:
    normalized = _normalize_key(key)
    if normalized in _NAME_KEYS:
        return REDACTED_NAME
    if normalized in _PHONE_KEYS:
        return REDACTED_PHONE
    if normalized in _EMAIL_KEYS:
        return REDACTED_EMAIL
    if normalized in _ADDRESS_KEYS:
        return REDACTED_ADDRESS
    return None


def _is_free_text_key(key: str) -> bool:
    return _normalize_key(key) in _FREE_TEXT_KEYS


def sanitize_text(text: str) -> str:
    """Scrub only explicit PII patterns from whitelist free-text fields."""
    if not text:
        return text
    sanitized = text
    sanitized = _EMAIL_RE.sub(REDACTED_EMAIL, sanitized)
    sanitized = _PHONE_RE.sub(REDACTED_PHONE, sanitized)
    sanitized = _OWNER_PHRASE_RE.sub(lambda _m: f"owner {REDACTED_NAME}", sanitized)
    sanitized = _INITIALS_RE.sub(REDACTED_NAME, sanitized)
    return sanitized


def sanitize_tool_result(payload: Any) -> Any:
    """Recursively sanitize structured fields and whitelist free-text fields."""
    return _sanitize_value(payload)


def _sanitize_value(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, Mapping):
        return {
            child_key: _sanitize_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, key=key) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, key=key) for item in value]
    if not isinstance(value, str):
        return value

    if key:
        replacement = _redaction_for_key(key)
        if replacement is not None:
            return replacement
        if _is_free_text_key(key):
            return sanitize_text(value)
    return value

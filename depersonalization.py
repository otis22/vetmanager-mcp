"""Centralized bearer-token response depersonalization helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


REDACTED_PHONE = "[redacted-phone]"
REDACTED_EMAIL = "[redacted-email]"
REDACTED_NAME = "[redacted-name]"
REDACTED_ADDRESS = "[redacted-address]"

# Stage 275: report columns are named by generated SQL from a Russian request,
# so the dictionary had to learn Russian. Only qualified names are listed here:
# a bare "имя" is as often a pet's or a product's as a person's, and redacting
# those would quietly ruin the report instead of protecting anyone.
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
    "фио",
    "владелец",
    "владелецпитомца",
    "хозяин",
    "клиент",
    "имяклиента",
    "имявладельца",
    "фамилия",
    "отчество",
    "фамилияимяотчество",
    "полноеимя",
    "контактноелицо",
})
_PHONE_KEYS = frozenset({
    "phone",
    "cellphone",
    "homephone",
    "workphone",
    "ownerphone",
    "телефон",
    "телефонклиента",
    "телефонвладельца",
    "мобильный",
    "мобильныйтелефон",
    "контактныйтелефон",
    "номертелефона",
})
_EMAIL_KEYS = frozenset({"email", "почта", "электроннаяпочта", "емейл", "имейл"})
_ADDRESS_KEYS = frozenset({"address", "адрес", "адресклиента", "адресдоставки"})
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
_DATE_OR_DATETIME_RE = re.compile(
    r"(?<!\d)(?:"
    r"(?:19\d{2}|20\d{2}|2100)-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])"
    r"|(?:0[1-9]|[12]\d|3[01])\.(?:0[1-9]|1[0-2])\.(?:19\d{2}|20\d{2}|2100)"
    r")(?:[T\s](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)?)?(?!\d)"
)
_PHONE_RE = re.compile(r"(?<!\[redacted-phone\])(?:\+?\d[\d\-\s().]{8,}\d)")
_OWNER_PHRASE_RE = re.compile(
    r"(?u)\b(?i:(?:владелец|хозяин|owner))\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё.\-]+(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё.\-]+){0,2}"
)
_INITIALS_RE = re.compile(
    r"(?u)\b[A-ZА-ЯЁ][a-zа-яё]{1,30}\s+[A-ZА-ЯЁ]\.\s?[A-ZА-ЯЁ]\."
)
# Stage 275: three capitalised Cyrillic words in a row. Two would catch a
# clinic or a street just as often as a person, so the two-word form is left
# to the other layers on purpose.
_FULL_NAME_RE = re.compile(
    r"(?u)\b[А-ЯЁ][а-яё]{1,30}\s+[А-ЯЁ][а-яё]{1,30}\s+[А-ЯЁ][а-яё]{1,30}\b"
)
# A patronymic gives a person away on its own: `-ович`, `-евна` and their kin
# are almost never part of a product or a clinic name, so a two-word "Пётр
# Сергеевич" is caught here even though a bare two-word name is not.
_PATRONYMIC_RE = re.compile(
    r"(?u)\b[А-ЯЁ][а-яё]{1,30}\s+[А-ЯЁ][а-яё]{1,30}(?:ович|евич|ьич|овна|евна|ична|инична)\b"
)
# A postal address written out. Anchored on the parts that only an address has
# — city, street, building, flat — so a service name cannot match by accident.
_ADDRESS_RE = re.compile(
    r"(?u)(?:\bг\.\s?[А-ЯЁ][а-яё\-]+[,\s]+)?"
    r"(?:ул\.|улица|пр-?т|проспект|пер\.|переулок|ш\.|шоссе|б-р|бульвар)\s?[А-ЯЁа-яё0-9\-\s]+"
    r"(?:[,\s]+д\.?\s?\d+[А-Яа-я]?)?(?:[,\s]+(?:кв\.?|оф\.?)\s?\d+)?"
)
# A run of digits that could be a Russian phone number. Bounded on purpose: a
# pet's microchip is fifteen digits and a barcode thirteen, and a report that
# loses those is broken rather than private.
_PHONE_LIKE_RE = re.compile(r"(?<![\d\-])\+?\d[\d\-\s().]{7,18}\d(?![\d\-])")
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
    date_spans = [match.span() for match in _DATE_OR_DATETIME_RE.finditer(text)]
    email_spans = [match.span() for match in _EMAIL_RE.finditer(text)]
    redactions = [(start, end, REDACTED_EMAIL) for start, end in email_spans]
    for phone_match in _PHONE_RE.finditer(text):
        start, end = phone_match.span()
        if any(
            date_start <= start and end <= date_end
            for date_start, date_end in date_spans
        ):
            continue
        date_free = _DATE_OR_DATETIME_RE.sub("", text[start:end])
        if not any(char.isdigit() for char in date_free):
            continue

        phone_fragments = [(start, end)]
        for email_start, email_end in email_spans:
            fragments_without_email: list[tuple[int, int]] = []
            for fragment_start, fragment_end in phone_fragments:
                if fragment_end <= email_start or fragment_start >= email_end:
                    fragments_without_email.append((fragment_start, fragment_end))
                    continue
                if fragment_start < email_start:
                    fragments_without_email.append((fragment_start, email_start))
                if email_end < fragment_end:
                    fragments_without_email.append((email_end, fragment_end))
            phone_fragments = fragments_without_email
        redactions.extend(
            (fragment_start, fragment_end, REDACTED_PHONE)
            for fragment_start, fragment_end in phone_fragments
        )

    sanitized_parts: list[str] = []
    position = 0
    for start, end, replacement in sorted(redactions, key=lambda item: (item[0], -item[1])):
        if start < position:
            continue
        sanitized_parts.append(text[position:start])
        sanitized_parts.append(replacement)
        position = end
    sanitized_parts.append(text[position:])
    sanitized = "".join(sanitized_parts)
    sanitized = _OWNER_PHRASE_RE.sub(lambda _m: f"owner {REDACTED_NAME}", sanitized)
    sanitized = _INITIALS_RE.sub(REDACTED_NAME, sanitized)
    return sanitized


def sanitize_report_value(text: str) -> str:
    """Clean a value from a report, whatever column it arrived in.

    Stage 275, layer two. A generated report names its columns itself, so the
    column name cannot be relied on; what is left is the value. Emails and
    phone-shaped numbers are recognisable enough to remove outright. Names are
    only taken in the forms that cannot be mistaken for a company or a street:
    three capitalised words, or a surname with initials.
    """
    if not text:
        return text
    cleaned = _EMAIL_RE.sub(REDACTED_EMAIL, text)
    cleaned = _FULL_NAME_RE.sub(REDACTED_NAME, cleaned)
    cleaned = _PATRONYMIC_RE.sub(REDACTED_NAME, cleaned)
    cleaned = _INITIALS_RE.sub(REDACTED_NAME, cleaned)
    cleaned = _ADDRESS_RE.sub(REDACTED_ADDRESS, cleaned)

    date_spans = [match.span() for match in _DATE_OR_DATETIME_RE.finditer(cleaned)]

    def _replace_phone(match: re.Match) -> str:
        start, end = match.span()
        # A date is digits and separators too: `2026-08-31 10:11` counts ten of
        # them, and a report stripped of its dates is worse than useless.
        if any(start < date_end and date_start < end for date_start, date_end in date_spans):
            return match.group(0)
        digits = [char for char in match.group(0) if char.isdigit()]
        # Ten and eleven digits is what a Russian phone has; anything longer is
        # a chip, a barcode or an internal identifier.
        return REDACTED_PHONE if 10 <= len(digits) <= 11 else match.group(0)

    return _PHONE_LIKE_RE.sub(_replace_phone, cleaned)


def sanitize_tool_result(payload: Any, *, report_mode: bool = False) -> Any:
    """Recursively sanitize structured fields and whitelist free-text fields.

    `report_mode` turns on the value-level cleaning that report rows need and
    ordinary tools must not get: their fields are predictable, and scrubbing
    every value there would cost real data for no gain.
    """
    return _sanitize_value(payload, report_mode=report_mode)


def _sanitize_value(value: Any, *, key: str | None = None, report_mode: bool = False) -> Any:
    if isinstance(value, Mapping):
        return {
            child_key: _sanitize_value(child_value, key=str(child_key), report_mode=report_mode)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(item, key=key, report_mode=report_mode) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_value(item, key=key, report_mode=report_mode) for item in value]
    if not isinstance(value, str):
        return value

    if key:
        replacement = _redaction_for_key(key)
        if replacement is not None:
            return replacement
        if _is_free_text_key(key):
            return sanitize_text(value)
    if report_mode:
        return sanitize_report_value(value)
    return value

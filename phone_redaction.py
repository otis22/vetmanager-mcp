"""Lightweight, shared recognition of phone-shaped personal data."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date


# A phone is either a contiguous 10–15 digit number, a deliberately structured
# local form (3–5/3/2/2), or an explicitly international grouped form.  The
# shape is intentionally narrower than "digits and separators": clinical rows
# and SVG coordinates must not become personal data.
_PHONE_RE = re.compile(
    r"(?<!\d)(?:"
    r"(?:\+\d{10,11}|[0-79]\d{9}|\d{11})"
    r"|\+\d{12,15}"
    r"|\+\d{1,3}(?:[ .-]\d{2,4}){2,4}"
    r"|(?:(?:\+\d{1,3}|8)[ .-]?)?\(\d{3,5}\)[ .-]?\d{3}[ .-]\d{2}[ .-]\d{2}"
    r"|(?:\+\d{1,3}|8)[ .-]?\(\d{3,5}\)[ .-]?\d{7}"
    r"|\+\d{1,3}[ .-]?\d{7,10}"
    r"|8[ .-]\d{7,10}"
    r"|\+\d{1,3}[ .-]?\d{3}[ .-]?\d{7}"
    r"|8[ .-]\d{3}[ .-]?\d{7}"
    r"|7(?:[ .-]|\()\d{3}\)?[ .-]\d{3}[ .-]\d{2}[ .-]\d{2}"
    r"|7(?:[ .-]|\()\d{3}\)?[ .-]?\d{7}"
    r"|(?:\+\d{1,3}|8)[ .-]\d{3,5}[ .-]\d{3}[ .-]\d{2}[ .-]\d{2}"
    r"|\d{3,5}-\d{3}-\d{2}-\d{2}"
    r"|\+\d{1,3}[ .-]\d{3,5}[ .-]\d{2}[ .-]\d{2}(?:[ .-]\d{2})?"
    r"|\d{3,5}-\d{2}-\d{2}(?:-\d{2})?"
    r"|(?<=тел\. )\d{3,5}[ .]\d{2}[ .]\d{2}"
    r")(?!\d)"
)
_UNIT_AFTER_RE = re.compile(
    r" ?(?:мкмоль/л|ммоль/л|мм рт\.ст\.|уд/мин|мкг|мл|мг|кг|px|pt|%|°[Cc]|°)(?![\w.])",
    re.IGNORECASE,
)
_UNIT_BEFORE_RE = re.compile(
    r"(?:мкмоль/л|ммоль/л|мм рт\.ст\.|уд/мин|мкг|мл|мг|кг|px|pt|%|°[Cc]|°) ?$",
    re.IGNORECASE,
)
_CONTACT_WORD_RE = re.compile(
    r"(?iu)\b(?:тел(?:ефон)?|звоните|звонить|перезвонить|с|до|после|в|на)\b"
)
_IDENTIFIER_BEFORE_RE = re.compile(r"(?iu)\b(?:id|ид|инн|chip|чип|microchip|микрочип|barcode|штрихкод)\s*[:=]?\s*$")


def iter_phone_matches(text: str) -> Iterator[re.Match[str]]:
    """Yield phone matches which are not the number in a clinical context."""
    for match in _PHONE_RE.finditer(text):
        if _has_clinical_context(text, match) or _is_valid_iso_date(match.group()):
            continue
        yield match


def redact_phone_numbers(text: str, replacement: str) -> str:
    """Replace shared phone matches without making callers share placeholders."""
    return _PHONE_RE.sub(
        lambda match: match.group(0)
        if _has_clinical_context(text, match) or _is_valid_iso_date(match.group())
        else replacement,
        text,
    )


def _has_clinical_context(text: str, match: re.Match[str]) -> bool:
    before = text[max(0, match.start() - 24):match.start()]
    after = text[match.end():match.end() + 24]
    if _CONTACT_WORD_RE.search(before) or _CONTACT_WORD_RE.search(after):
        return False
    if _IDENTIFIER_BEFORE_RE.search(before):
        return True
    return bool(
        _UNIT_AFTER_RE.match(after)
        or _UNIT_BEFORE_RE.search(before)
    )


def _is_valid_iso_date(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True

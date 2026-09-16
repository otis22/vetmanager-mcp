"""Fail-closed redaction for the Vetmanager ``properties`` entity."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping


REDACTED_SECRET = "[redacted:secret]"

# Exact names found in the read-only Vetmanager source are retained as a
# regression list. The pattern below is the future-proof protection: a newly
# introduced setting must be redacted before somebody updates this set.
KNOWN_SECRET_PROPERTY_NAMES = frozenset({
    "abaxxis_login", "abaxxis_pass", "admin_api_token", "alpha_sms_api_key",
    "auth_barcode_key", "auth_key", "auth_pw", "backup_downloader_api",
    "clinic_billing_key", "clinic_token", "crm_key", "crm_token",
    "freshdesk_api_email", "freshdesk_api_password", "idexx_api_key",
    "ikassa.access_token", "ikassa.refresh_token", "kyivstar.sms.token",
    "kyivstar_client_secret", "lm_login", "lm_password", "mailchimp_api_key",
    "mailserver_login", "mailserver_pass", "pdf_scaner_api_key", "rest_api_key",
    "sms_center_login", "sms_center_password", "unisender_api_number",
    "vats_api_key", "vats_api_salt", "vm_key", "voip_login", "voip_password",
    "ws_api_keys", "youtrack_login", "youtrack_password", "zoetis_login", "zoetis_pass",
})

_SECRET_NAME_RE = re.compile(
    r"api|key|token|secret|pass|password|passwd|pwd|salt|auth|credential|billing|"
    r"login|access|cert|private|signature|hmac|pin|otp|sid|hash|bearer|"
    r"пароль|(?<![а-яё])ключ|токен|секрет|логин",
    re.IGNORECASE,
)
_JWT_RE = re.compile(r"^eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}$")
_PREFIX_TOKEN_RE = re.compile(
    r"^(?:"
    r"(?:sk[-_]|pk_|rk_)[A-Za-z0-9_-]{8,}|"
    r"AIza[A-Za-z0-9_-]{12,}|"
    r"AKIA[A-Z0-9]{12,}|"
    r"gh[ops]_[A-Za-z0-9_-]{12,}|"
    r"xox[abposr]-[A-Za-z0-9_-]{12,}|"
    r"ya29\.[A-Za-z0-9._-]{12,}|"
    r"glpat-[A-Za-z0-9_-]{12,}|"
    r"hf_[A-Za-z0-9_-]{12,}"
    r")$"
)
_BEARER_TOKEN_RE = re.compile(r"^bearer\s+[^\s]{12,}$", re.IGNORECASE)
_URL_SECRET_QUERY_RE = re.compile(
    r"https?://[^\s]*[?&][^=&#\s]*(?:key|token|secret|pass|auth|sig)[^=&#\s]*=[^&#\s]+",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"^[0-9a-fA-F]{24,}$")
_ALNUM_TOKEN_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z0-9]{24,}$")
_BASE64_TOKEN_RE = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)[A-Za-z0-9+/]{22,}={0,2}$"
)
_BASE64URL_TOKEN_RE = re.compile(r"^(?=.*\d)[A-Za-z0-9_-]{32,}$")
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_PATH_RE = re.compile(r"^/")
_CREDENTIAL_PAIR_RE = re.compile(
    r"^[A-Za-z0-9._-]{3,}:(?=[^\s]{6,}$)(?=[^\s]*[0-9!@#$%^&*])[A-Za-z0-9._!@#$%^&*+-]+$"
)


def is_secret_property_name_or_title(row: Mapping[str, object]) -> bool:
    """Return whether an upstream property label is unsafe to disclose."""
    for field in ("property_name", "property_title"):
        value = row.get(field)
        if isinstance(value, str):
            normalized = value.casefold()
            if normalized in KNOWN_SECRET_PROPERTY_NAMES or _SECRET_NAME_RE.search(normalized):
                return True
    return False


def looks_like_secret_value(value: object) -> bool:
    """Recognise conservative, ASCII-only credential forms without logging them."""
    if not isinstance(value, str) or not value:
        return False
    if (
        _JWT_RE.fullmatch(value)
        or _PREFIX_TOKEN_RE.fullmatch(value)
        or _BEARER_TOKEN_RE.fullmatch(value)
    ):
        return True
    if _URL_SECRET_QUERY_RE.search(value) or _CREDENTIAL_PAIR_RE.fullmatch(value):
        return True
    if _UUID_RE.fullmatch(value) or _PATH_RE.match(value) or value.isdecimal():
        return False
    return bool(
        _HEX_RE.fullmatch(value)
        or _ALNUM_TOKEN_RE.fullmatch(value)
        or _BASE64_TOKEN_RE.fullmatch(value)
        or _BASE64URL_TOKEN_RE.fullmatch(value)
    )


def sanitize_properties_response(response: object) -> object:
    """Copy one ``/properties`` list response and redact unsafe values.

    Deliberately accepts malformed upstream shapes unchanged: output validation
    belongs to the HTTP layer, while this safety net must never turn a safe
    upstream error into a message containing a raw property value.
    """
    if not isinstance(response, Mapping):
        return response
    result = copy.deepcopy(response)
    data = result.get("data")
    if not isinstance(data, dict):
        return result
    rows = data.get("properties")
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        if is_secret_property_name_or_title(row) or looks_like_secret_value(row.get("property_value")):
            row["property_value"] = REDACTED_SECRET
    return result

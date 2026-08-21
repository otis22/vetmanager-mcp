"""Shared privacy helpers for audit logs and operator-facing reports.

`mask_email` was originally inlined in `scripts/product_metrics_report.py`;
Stage 155 extracted it so `auth/bearer.py` can reuse the same redaction
when writing IP-denied audit payloads.

`extract_client_ip_tail` produces a privacy-safe trailing segment (last
octet for IPv4, last hextet for IPv6) so denied-event logs identify the
likely subnet without leaking the full client IP.
"""

from __future__ import annotations

import ipaddress

import json
from collections.abc import Mapping, Sequence

from fastmcp.exceptions import ToolError


_GLOBAL_SENSITIVE_OUTPUT_FIELDS = frozenset({
    "passport_series",
    "passwd",
    "last_change_pwd_date",
})
_STAFF_SENSITIVE_OUTPUT_FIELDS = frozenset({"login", "user_inn", "calc_percents"})
_STAFF_CONTAINER_FIELDS = frozenset({"user", "users", "doctor", "doctor_data", "closedUser"})


def redact_sensitive_output_fields(value, *, _staff_record: bool = False):
    """Redact confirmed output fields from JSON-like and Pydantic values.

    ``passport_series``, ``passwd`` and ``last_change_pwd_date`` are globally
    unambiguous. The generic names ``login``, ``user_inn`` and ``calc_percents``
    are removed only from staff containers confirmed by the OpenAPI contract.
    """
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return redact_sensitive_output_fields(
                model_dump(mode="json"), _staff_record=_staff_record,
            )
        except Exception:
            # Keep an object whose serializer has a non-standard signature or
            # rejects Python mode; the wrapper must not break its tool result.
            return value
    if isinstance(value, Mapping):
        return {
            key: redact_sensitive_output_fields(
                item, _staff_record=key in _STAFF_CONTAINER_FIELDS,
            )
            for key, item in value.items()
            if key not in _GLOBAL_SENSITIVE_OUTPUT_FIELDS
            and not (_staff_record and key in _STAFF_SENSITIVE_OUTPUT_FIELDS)
        }
    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_output_fields(item, _staff_record=_staff_record)
            for item in value
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            redact_sensitive_output_fields(item, _staff_record=_staff_record)
            for item in value
        ]
    return value


def redact_tool_error(exc: ToolError) -> ToolError:
    """Redact structured base ToolError arguments without changing subclasses."""
    if type(exc) is not ToolError:
        return exc
    redacted_args = tuple(_redact_error_argument(value) for value in exc.args)
    return ToolError(*redacted_args)


def _redact_error_argument(value):
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return value
        if not isinstance(decoded, (dict, list)):
            return value
        redacted = redact_sensitive_output_fields(decoded)
        if redacted == decoded:
            return value
        return json.dumps(redacted, ensure_ascii=False, sort_keys=True)
    return redact_sensitive_output_fields(value)


def mask_email(email: str | None) -> str:
    """Return a PII-friendly masked email: `al***@ex***.com`."""
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if "." not in domain:
        return "***@***"
    domain_name, _, tld = domain.rpartition(".")
    if len(local) < 3 or len(domain_name) < 3:
        return "***@***"
    return f"{local[:2]}***@{domain_name[:2]}***.{tld}"


def extract_client_ip_tail(ip: str | None) -> str:
    """Return last segment of an IP for privacy-safe audit logging.

    IPv4 (`192.168.1.5`) → last octet (`5`).
    IPv6 (`2001:db8::42`, `::1`) → last hextet (`42`, `1`).
    Unknown / missing → `unknown`.
    """
    if not ip or ip == "unknown":
        return "unknown"
    if ":" in ip:
        return ip.split(":")[-1] or "unknown"
    if "." in ip:
        return ip.split(".")[-1]
    return "unknown"


def mask_ip_to_network(ip: str | None) -> str:
    """Keep a diagnostic network while removing an individual host address."""
    if not ip or ip == "unknown":
        return "unknown"
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return "unknown"
    prefix = 24 if address.version == 4 else 64
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False).network_address)

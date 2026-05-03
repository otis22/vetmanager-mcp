"""Shared privacy helpers for audit logs and operator-facing reports.

`mask_email` was originally inlined in `scripts/product_metrics_report.py`;
Stage 155 extracted it so `auth/bearer.py` can reuse the same redaction
when writing IP-denied audit payloads.

`extract_client_ip_tail` produces a privacy-safe trailing segment (last
octet for IPv4, last hextet for IPv6) so denied-event logs identify the
likely subnet without leaking the full client IP.
"""

from __future__ import annotations


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

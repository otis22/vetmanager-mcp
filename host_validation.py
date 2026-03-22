"""Shared validation helpers for resolved Vetmanager clinic origins."""

from __future__ import annotations

from urllib.parse import urlparse

from exceptions import HostResolutionError

ALLOWED_HOST_SUFFIXES = ("vetmanager.cloud", "vetmanager2.ru")


def validate_resolved_vetmanager_origin(host: str, *, domain: str) -> str:
    """Validate billing-resolved origin and return normalized HTTPS origin."""
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise HostResolutionError(f"Resolved host must use HTTPS for domain '{domain}'.")
    if parsed.username or parsed.password:
        raise HostResolutionError(f"Resolved host must not include userinfo for domain '{domain}'.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HostResolutionError(f"Resolved host has invalid port for domain '{domain}'.") from exc
    if port not in (None, 443):
        raise HostResolutionError(
            f"Resolved host must not use a custom port for domain '{domain}'."
        )
    if parsed.path not in ("", "/") or parsed.params or parsed.query or parsed.fragment:
        raise HostResolutionError(
            f"Resolved host must be a bare origin for domain '{domain}'."
        )
    if not any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES):
        raise HostResolutionError(f"Resolved host is not allowlisted for domain '{domain}'.")
    if not hostname:
        raise HostResolutionError(f"Resolved host is missing hostname for domain '{domain}'.")
    return f"https://{hostname}"

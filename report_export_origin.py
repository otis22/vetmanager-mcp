"""Validate and resolve untrusted Vetmanager report-export locators."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from ipaddress import ip_address
import os
import socket
from urllib.parse import SplitResult, urlsplit

import report_export


ALLOWED_ORIGINS_ENV = "REPORT_EXPORT_ALLOWED_ORIGINS"
DNS_TIMEOUT_SECONDS = 5.0
_DNS_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="report-export-dns")
Resolver = Callable[[str], Awaitable[Sequence[str]]]


@dataclass(frozen=True)
class ExportTarget:
    locator: str
    hostname: str
    origin: str
    addresses: tuple[str, ...]


def _security_error() -> report_export.ReportExportError:
    return report_export.ReportExportError(
        "The export storage address was rejected by MCP security policy."
    )


def _canonical_host(raw: str) -> str:
    host = raw.rstrip(".").lower()
    if not host or "*" in host:
        raise ValueError("invalid hostname")
    try:
        return str(ip_address(host))
    except ValueError:
        return host.encode("idna").decode("ascii")


def _canonical_origin(parsed: SplitResult) -> tuple[str, str]:
    try:
        port = parsed.port
        hostname = _canonical_host(parsed.hostname or "")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("invalid origin") from exc
    if parsed.scheme.lower() != "https" or parsed.username is not None or parsed.password is not None:
        raise ValueError("invalid origin")
    if port not in (None, 443):
        raise ValueError("invalid origin")
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    return f"https://{rendered_host}", hostname


def parse_allowed_origins(raw: str | None = None) -> frozenset[str]:
    value = os.environ.get(ALLOWED_ORIGINS_ENV, "") if raw is None else raw
    if not value.strip():
        return frozenset()
    origins: set[str] = set()
    try:
        for item in value.split(","):
            parsed = urlsplit(item.strip())
            if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise ValueError("invalid origin suffix")
            origin, _ = _canonical_origin(parsed)
            origins.add(origin)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {ALLOWED_ORIGINS_ENV} configuration.") from exc
    return frozenset(origins)


def validate_allowed_origins_config() -> None:
    parse_allowed_origins()


def _resolve_sync(hostname: str) -> tuple[str, ...]:
    addresses = {
        item[4][0]
        for item in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        if item[0] in (socket.AF_INET, socket.AF_INET6)
    }
    return tuple(sorted(addresses, key=lambda value: (ip_address(value).version, value)))


async def resolve_public_addresses(hostname: str) -> tuple[str, ...]:
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_DNS_EXECUTOR, _resolve_sync, hostname)
    return await asyncio.wait_for(future, timeout=DNS_TIMEOUT_SECONDS)


async def resolve_export_target(locator: str, *, resolver: Resolver = resolve_public_addresses) -> ExportTarget:
    try:
        parsed = urlsplit(locator)
        origin, hostname = _canonical_origin(parsed)
    except ValueError:
        raise _security_error() from None

    allowed = parse_allowed_origins()
    if allowed and origin not in allowed:
        raise report_export.ReportExportError(f"Export origin is not in allowlist: {origin}.")

    try:
        addresses = tuple(dict.fromkeys(await resolver(hostname)))
        parsed_addresses = [ip_address(value) for value in addresses]
    except (OSError, UnicodeError, ValueError, asyncio.TimeoutError):
        raise _security_error() from None
    if not parsed_addresses or any(
        not address.is_global
        or address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        for address in parsed_addresses
    ):
        raise _security_error()
    ordered = tuple(
        str(address) for address in sorted(parsed_addresses, key=lambda value: value.version)
    )
    return ExportTarget(locator=locator, hostname=hostname, origin=origin, addresses=ordered)

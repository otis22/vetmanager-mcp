"""Typed, low-cardinality classification for upstream transport errors."""

from __future__ import annotations

import ssl

import httpx


def _caused_by_tls_verification(exc: BaseException) -> bool:
    """Walk the cause chain for a certificate-verification failure.

    Stage 292: a clinic serving its certificate without the intermediate link
    surfaces as a plain `ConnectError`, indistinguishable from a DNS miss. The
    distinction matters: one is fixed on their server, the other is not.

    Deliberately narrower than `ssl.SSLError`: a protocol mismatch
    (`WRONG_VERSION_NUMBER`) is also an SSL error, and answering it with
    "fix your certificate chain" sends the operator to the wrong place
    (external review finding, 04.09.2026). Matched by type, never by text.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        current = current.__cause__ or current.__context__
    return False


def classify_transport_error(exc: httpx.RequestError) -> str:
    """Return a stable transport reason without inspecting exception text."""
    if _caused_by_tls_verification(exc):
        return "tls_verification_failed"
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    return "network_error"


def classify_http_status(status_code: int) -> str:
    """Collapse status codes into bounded failure classes."""
    return "http_4xx" if 400 <= status_code < 500 else "http_5xx"

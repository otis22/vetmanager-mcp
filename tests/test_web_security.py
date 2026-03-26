"""Regression tests for trusted proxy handling in web security helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from starlette.requests import Request

from auth_audit import get_request_audit_metadata
from web_security import get_request_ip, resolve_client_ip

pytestmark = pytest.mark.security


def _make_request(
    *,
    client_host: str,
    forwarded_for: str | None = None,
    user_agent: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    if user_agent is not None:
        headers.append((b"user-agent", user_agent.encode("ascii")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/login",
        "headers": headers,
        "client": (client_host, 12345),
    }
    return Request(scope)


def test_resolve_client_ip_ignores_forwarded_chain_without_trusted_proxy(monkeypatch):
    monkeypatch.delenv("WEB_TRUSTED_PROXY_IPS", raising=False)

    resolved = resolve_client_ip(
        client_host="203.0.113.10",
        forwarded_for="198.51.100.42, 203.0.113.7",
    )

    assert resolved == "203.0.113.10"


def test_resolve_client_ip_uses_forwarded_chain_for_trusted_proxy(monkeypatch):
    monkeypatch.setenv("WEB_TRUSTED_PROXY_IPS", "127.0.0.1, 10.0.0.1")

    resolved = resolve_client_ip(
        client_host="127.0.0.1",
        forwarded_for="198.51.100.42, 203.0.113.7",
    )

    assert resolved == "198.51.100.42"


def test_get_request_ip_uses_shared_trusted_proxy_policy(monkeypatch):
    monkeypatch.setenv("WEB_TRUSTED_PROXY_IPS", "127.0.0.1")

    request = _make_request(
        client_host="127.0.0.1",
        forwarded_for="198.51.100.42, 203.0.113.7",
    )

    assert get_request_ip(request) == "198.51.100.42"


def test_get_request_audit_metadata_ignores_spoofed_forwarded_for_without_trusted_proxy(
    monkeypatch,
):
    monkeypatch.delenv("WEB_TRUSTED_PROXY_IPS", raising=False)
    request = _make_request(
        client_host="203.0.113.10",
        forwarded_for="198.51.100.42",
        user_agent="pytest-agent",
    )

    with patch(
        "fastmcp.server.dependencies.get_http_request",
        return_value=request,
    ):
        ip_address, user_agent = get_request_audit_metadata()

    assert ip_address == "203.0.113.10"
    assert user_agent == "pytest-agent"


@pytest.mark.asyncio
async def test_read_form_rejects_oversized_payload():
    """_read_form must reject payloads exceeding MAX_FORM_PAYLOAD_BYTES."""
    import httpx
    from server import mcp
    from web import MAX_FORM_PAYLOAD_BYTES

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    oversized_body = "x=" + "a" * (MAX_FORM_PAYLOAD_BYTES + 1)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/register",
            content=oversized_body,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 413


def test_password_validation_rejects_weak_passwords():
    """Password validator must enforce minimum complexity."""
    from web_auth import _validate_password_strength

    # Too short
    with pytest.raises(ValueError, match="не менее"):
        _validate_password_strength("Abc1")

    # No uppercase
    with pytest.raises(ValueError, match="заглавную"):
        _validate_password_strength("abcdefgh123")

    # No lowercase
    with pytest.raises(ValueError, match="строчную"):
        _validate_password_strength("ABCDEFGH123")

    # No digit
    with pytest.raises(ValueError, match="цифру"):
        _validate_password_strength("Abcdefghij")

    # Valid password — should not raise
    _validate_password_strength("Strong-Pass-123")

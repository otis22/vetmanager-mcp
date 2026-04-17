"""Stage 89 — security hot-fix: Sentry sanitizer + deploy defaults + SITE_BASE_URL.

- Pattern-based sanitizer in error_tracking redacts any header/body/cookie/
  query-string/extra key containing token|key|secret|auth|api|cookie|bearer|
  password|credential|session|csrf.
- Safe observability keys (x-request-id, x-correlation-id) are preserved.
- Deploy scripts no longer default to the old SimpleCloud host.
- landing_page / web_html honor SITE_BASE_URL env var for self-hosted deploys.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from error_tracking import _sanitize_event


REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Sentry sanitizer ────────────────────────────────────────────────────────


def test_sanitizer_redacts_vm_user_token_header():
    """The baseline allowlist missed x-user-token — pattern-based match
    must catch it now."""
    event = {"request": {"headers": {"x-user-token": "secret-raw-token"}}}
    _sanitize_event(event, None)
    assert event["request"]["headers"]["x-user-token"] == "[Filtered]"


def test_sanitizer_redacts_all_credential_shaped_header_names():
    event = {"request": {"headers": {
        "authorization": "Bearer abc",
        "cookie": "sid=xxx",
        "x-vm-api-key": "k",
        "x-app-secret": "s",
        "x-session-id": "ssid",
        "x-password": "p",
        "csrf-token": "c",
    }}}
    _sanitize_event(event, None)
    for key in event["request"]["headers"]:
        assert event["request"]["headers"][key] == "[Filtered]", (
            f"{key} was not redacted"
        )


def test_sanitizer_preserves_correlation_id_header():
    """correlation ID is not a secret — must survive redaction."""
    event = {"request": {"headers": {
        "x-correlation-id": "corr-xyz",
        "x-request-id": "req-abc",
        "user-agent": "curl/8",
    }}}
    _sanitize_event(event, None)
    assert event["request"]["headers"]["x-correlation-id"] == "corr-xyz"
    assert event["request"]["headers"]["x-request-id"] == "req-abc"
    assert event["request"]["headers"]["user-agent"] == "curl/8"


def test_sanitizer_redacts_cookies_and_query_and_body():
    event = {"request": {
        "headers": {},
        "cookies": {"session_token": "sssss"},
        "query_string": {"api_key": "kkkkk", "page": "1"},
        "data": {"password": "pppp", "username": "u"},
    }}
    _sanitize_event(event, None)
    assert event["request"]["cookies"]["session_token"] == "[Filtered]"
    assert event["request"]["query_string"]["api_key"] == "[Filtered]"
    assert event["request"]["query_string"]["page"] == "1"
    assert event["request"]["data"]["password"] == "[Filtered]"
    assert event["request"]["data"]["username"] == "u"


def test_sanitizer_redacts_extra_context():
    event = {"extra": {"bearer_token": "t", "domain": "vetmanager.cloud"}}
    _sanitize_event(event, None)
    assert event["extra"]["bearer_token"] == "[Filtered]"
    # "domain" is not inherently sensitive, not matched by any pattern.
    assert event["extra"]["domain"] == "vetmanager.cloud"


def test_sanitizer_redacts_webhook_signature_family():
    """Stage 89 hardening: signature/jwt/hmac/otp/passphrase patterns."""
    event = {"request": {"headers": {
        "x-signature": "sig123",
        "stripe-signature": "stripe-sig",
        "x-hub-signature-256": "hub256",
        "jwt-token": "jwt-body",
        "x-hmac": "hmac-body",
        "x-otp-code": "otpotp",
        "passphrase": "ppp",
    }}}
    _sanitize_event(event, None)
    for key, value in event["request"]["headers"].items():
        assert value == "[Filtered]", f"{key} not redacted"


def test_sanitizer_does_not_redact_api_version_headers():
    """`api` substring match should not swallow version/protocol metadata."""
    event = {"request": {"headers": {
        "api-version": "2024-06",
        "x-api-version": "v1",
        "retry-after": "120",
        "etag": "W/\"abc\"",
    }}}
    _sanitize_event(event, None)
    assert event["request"]["headers"]["api-version"] == "2024-06"
    assert event["request"]["headers"]["x-api-version"] == "v1"
    assert event["request"]["headers"]["retry-after"] == "120"
    assert event["request"]["headers"]["etag"] == "W/\"abc\""


# ── Deploy defaults ─────────────────────────────────────────────────────────


def test_deploy_scripts_no_longer_default_to_legacy_simplecloud_domain():
    """Post stage 89 grep — all shipping deploy scripts + GHA workflow
    must not hardcode the old SimpleCloud prod host."""
    patterns_to_check = [
        REPO_ROOT / "scripts" / "deploy_server.sh",
        REPO_ROOT / "scripts" / "init_server.sh",
        REPO_ROOT / "scripts" / "renew_cert_if_needed.sh",
        REPO_ROOT / "scripts" / "sync_and_deploy_server.sh",
        REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml",
    ]
    for path in patterns_to_check:
        content = path.read_text(encoding="utf-8")
        assert "342915.simplecloud.ru" not in content, (
            f"{path.relative_to(REPO_ROOT)} still references legacy domain"
        )


# ── SITE_BASE_URL in landing + web_html ─────────────────────────────────────


def test_landing_page_honors_site_base_url_env(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://my-clinic.example.org")
    # Re-import to pick up new env — landing_page resolves at call time
    from landing_page import render_landing_page

    html = render_landing_page()
    assert "https://my-clinic.example.org/" in html or "my-clinic.example.org/mcp" in html
    # Default prod URL should not leak into self-hosted rendering.
    assert "vetmanager-mcp.vromanichev.ru" not in html


def test_landing_page_default_url_when_env_unset(monkeypatch):
    monkeypatch.delenv("SITE_BASE_URL", raising=False)
    from landing_page import render_landing_page

    html = render_landing_page()
    # Prod default keeps rendering correctly.
    assert "https://vetmanager-mcp.vromanichev.ru/" in html


def test_web_html_account_page_uses_site_base_url(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://my-clinic.example.org")
    from web_html import render_account_page

    account = MagicMock()
    account.id = 1
    account.email = "user@example.org"
    html = render_account_page(
        account,
        csrf_token="c",
        script_nonce="n",
        active_connection_count=0,
        bearer_token_count=0,
        active_connection=None,
        integration_health_status="active",
        integration_health_reason="",
        bearer_tokens=[],
        issued_raw_token="demo-token-xyz",
    )
    assert "https://my-clinic.example.org/mcp" in html
    assert "vetmanager-mcp.vromanichev.ru" not in html

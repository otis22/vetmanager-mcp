"""Stage 196 — activation UX: mobile Vetmanager connection step.

Covers domain normalization, mobile input attributes, error/success
visibility (role=alert + autoscroll + Russian next-step texts), submit lock,
API-key reveal toggle, conditional reauth button, and checked-card highlight.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

import storage
from domain_validation import normalize_domain_input, validate_domain
from exceptions import VetmanagerError
from server import mcp
from storage_models import Account, VetmanagerConnection
from web_html import render_account_page
from web_routes_account import _integration_error_text

from tests.test_web_auth import (
    TEST_ENCRYPTION_KEY,
    _post_with_csrf,
    _prepare_web_db,
)


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


class _Connection:
    auth_mode = "domain_api_key"
    domain = "clinic"
    status = "active"


def _account_page(**overrides) -> str:
    account = Account(id=1, email="owner@example.org", status="active")
    kwargs = dict(
        csrf_token="csrf-token",
        script_nonce="nonce",
        active_connection_count=0,
        bearer_token_count=0,
        active_connection=None,
        integration_health_status="unknown",
        integration_health_reason="ok",
        bearer_tokens=[],
        oauth_grants=[],
        activation_now=NOW,
    )
    kwargs.update(overrides)
    return render_account_page(account, **kwargs)


# ── 196.2: domain normalization ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("myclinic", "myclinic"),
        ("Myclinic", "myclinic"),
        ("MYCLINIC", "myclinic"),
        ("  myclinic  ", "myclinic"),
        ("myclinic.vetmanager.ru", "myclinic"),
        ("myclinic.vetmanager.cloud", "myclinic"),
        ("https://myclinic.vetmanager.ru", "myclinic"),
        ("https://myclinic.vetmanager.ru/", "myclinic"),
        ("http://Myclinic.vetmanager.ru/some/path?x=1", "myclinic"),
        ("my-clinic2", "my-clinic2"),
    ],
)
def test_validate_domain_normalizes_mobile_and_pasted_input(raw: str, expected: str) -> None:
    assert normalize_domain_input(raw) == expected
    assert validate_domain(raw) == expected


@pytest.mark.parametrize("raw", ["", "my clinic", "клиника", "-bad", "a" * 80])
def test_validate_domain_still_rejects_invalid_shapes(raw: str) -> None:
    with pytest.raises(VetmanagerError):
        validate_domain(raw)


@pytest.mark.asyncio
@respx.mock
async def test_integration_save_accepts_capitalized_domain_from_mobile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact prod failure: mobile keyboard capitalizes the first letter."""
    from web_auth import register_account

    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session, email="mobile@example.com", password="Integration-Pass-123"
        )

    respx.get("https://billing-api.vetmanager.cloud/host/mobclinic").mock(
        return_value=httpx.Response(
            200, json={"data": {"url": "https://mobclinic.vetmanager.cloud"}}
        )
    )
    respx.get("https://mobclinic.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=True
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "mobile@example.com", "password": "Integration-Pass-123"},
        )
        response = await _post_with_csrf(
            client,
            "/account/integration",
            data={"domain": "  Https://Mobclinic.vetmanager.ru/ ", "api_key": "good-key"},
            page_path="/account",
        )

    assert response.status_code == 200
    assert "Интеграция Vetmanager сохранена" in response.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(VetmanagerConnection, 1)
    assert stored is not None
    assert stored.domain == "mobclinic"

    await engine.dispose()
    storage.reset_storage_state()


def test_domain_inputs_carry_mobile_attributes_and_format_hint() -> None:
    html = _account_page()
    for testid in ("integration-domain", "integration-domain-user-token"):
        field = html.split(f'data-testid="{testid}"')[0].rsplit("<input", 1)[1]
        assert 'autocapitalize="none"' in field
        assert 'autocorrect="off"' in field
        assert 'spellcheck="false"' in field
    login_field = html.split('data-testid="integration-vm-login"')[0].rsplit("<input", 1)[1]
    assert 'autocapitalize="none"' in login_field
    assert html.count("мы возьмём из него поддомен") == 2


# ── 196.3: error texts and visibility ────────────────────────────────────────


def test_integration_error_text_maps_known_failures_to_russian_next_steps() -> None:
    assert "поддомен" in _integration_error_text(
        VetmanagerError("Invalid Vetmanager domain format. Use clinic subdomain like 'myclinic'.")
    )
    from exceptions import AuthError, HostResolutionError, VetmanagerTimeoutError

    assert "API key" in _integration_error_text(AuthError("Invalid Vetmanager API key."))
    assert "логин или пароль" in _integration_error_text(
        AuthError("Invalid Vetmanager login or password.")
    )
    assert "не отвечает" in _integration_error_text(
        VetmanagerTimeoutError("Vetmanager connection test timed out.")
    )
    assert "Не нашли клинику" in _integration_error_text(
        HostResolutionError("billing lookup failed")
    )
    assert _integration_error_text(ValueError("custom message")) == "custom message"


def test_integration_error_renders_alert_with_autoscroll() -> None:
    html = _account_page(integration_error="Что-то пошло не так")
    assert 'id="integration-error" role="alert" data-autoscroll="true"' in html


def test_integration_success_renders_status_with_cta_to_token_section() -> None:
    html = _account_page(
        active_connection=_Connection(),
        integration_health_status="active",
        integration_success="Интеграция Vetmanager сохранена.",
    )
    assert 'id="integration-success" role="status" data-autoscroll="true"' in html
    assert 'data-testid="integration-success-cta"' in html
    assert 'href="#token-section"' in html


# ── 196.5: submit lock and API key reveal ────────────────────────────────────


def test_integration_form_has_submit_lock_and_status_slot() -> None:
    html = _account_page()
    assert 'data-submit-lock="Проверяем подключение к Vetmanager' in html
    assert "data-submit-status" in html
    assert "button.disabled = true" in html


def test_api_key_field_has_reveal_toggle() -> None:
    html = _account_page()
    assert 'data-testid="integration-api-key-reveal"' in html
    assert 'data-reveal-target="integration-api-key-input"' in html
    assert "input.type = reveal ? 'text' : 'password'" in html


# ── 196.6: reauth button visibility and selection highlight ─────────────────


def test_reauth_button_hidden_for_new_and_healthy_accounts() -> None:
    assert "integration-reauth-submit" not in _account_page()
    assert "integration-reauth-submit" not in _account_page(
        active_connection=_Connection(), integration_health_status="active"
    )


def test_reauth_button_shown_when_reauth_required() -> None:
    html = _account_page(
        active_connection=_Connection(),
        integration_health_status="reauth_required",
    )
    assert 'data-testid="integration-reauth-submit"' in html


def test_choice_card_highlight_and_disabled_styles_present() -> None:
    html = _account_page()
    assert ".choice-option:has(input:checked)" in html
    assert "button:disabled" in html
    assert "input:disabled, select:disabled" in html

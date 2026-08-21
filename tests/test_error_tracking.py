"""Regression coverage for optional error tracking bootstrap."""

from unittest.mock import MagicMock, patch

import error_tracking


def test_configure_error_tracking_noops_without_dsn(monkeypatch):
    monkeypatch.delenv("ERROR_TRACKING_DSN", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    assert error_tracking.configure_error_tracking() is False


def test_handled_connection_capture_noops_when_tracking_is_disabled(monkeypatch):
    monkeypatch.setattr(error_tracking, "_configured", False)
    with patch.object(error_tracking.sentry_sdk, "capture_exception") as capture:
        error_tracking.capture_handled_connection_failure(RuntimeError("boom"), account_id=42)
    capture.assert_not_called()


def test_handled_connection_capture_uses_only_account_id_tag(monkeypatch):
    scope = MagicMock()
    scope_context = MagicMock()
    scope_context.__enter__.return_value = scope
    monkeypatch.setattr(error_tracking, "_configured", True)
    monkeypatch.setattr(error_tracking.sentry_sdk, "is_initialized", lambda: True)
    with (
        patch.object(error_tracking.sentry_sdk, "push_scope", return_value=scope_context),
        patch.object(error_tracking.sentry_sdk, "capture_exception") as capture,
    ):
        error_tracking.capture_handled_connection_failure(RuntimeError("clinic.example secret"), account_id=42)

    scope.set_tag.assert_any_call("handled_connection_failure", "true")
    scope.set_tag.assert_any_call("account_id", "42")
    scope.clear_breadcrumbs.assert_called_once_with()
    capture.assert_called_once()


def test_handled_connection_event_keeps_stack_but_redacts_message_and_locals():
    event = {
        "tags": {"handled_connection_failure": "true", "account_id": "42"},
        "exception": {"values": [{"value": "https://clinic.example secret", "stacktrace": {
            "frames": [{"filename": "service.py", "vars": {
                "domain": "clinic.example", "login": "alice@example.com", "password": "secret"
            }}]
        }}]},
        "request": {"data": {"domain": "clinic.example", "vm_login": "alice@example.com"}},
    }

    sanitized = error_tracking._sanitize_event(event, hint={})

    frame = sanitized["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert sanitized["exception"]["values"][0]["value"] == "[Filtered]"
    assert frame["vars"] == {"domain": "[Filtered]", "login": "[Filtered]", "password": "[Filtered]"}
    assert sanitized["tags"]["account_id"] == "42"
    assert sanitized["request"]["data"]["domain"] == "clinic.example"
    assert sanitized["request"]["data"]["vm_login"] == "[Filtered]"


def test_sanitize_event_redacts_ip_address_keys_but_not_clinic_domain():
    event = {"request": {"data": {
        "domain": "clinic.example", "client_ip": "203.0.113.42", "remote_addr": "2001:db8::42"
    }}, "user": {"ip_address": "203.0.113.42"}}

    sanitized = error_tracking._sanitize_event(event, hint={})

    assert sanitized["request"]["data"] == {
        "domain": "clinic.example", "client_ip": "[Filtered]", "remote_addr": "[Filtered]"
    }
    assert sanitized["user"]["ip_address"] == "[Filtered]"


def test_sanitize_event_redacts_sensitive_request_headers():
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer top-secret",
                "Cookie": "session=secret",
                "X-REST-API-KEY": "api-secret",
                "User-Agent": "pytest",
            }
        }
    }

    sanitized = error_tracking._sanitize_event(event, hint={})

    assert sanitized["request"]["headers"]["Authorization"] == "[Filtered]"
    assert sanitized["request"]["headers"]["Cookie"] == "[Filtered]"
    assert sanitized["request"]["headers"]["X-REST-API-KEY"] == "[Filtered]"
    assert sanitized["request"]["headers"]["User-Agent"] == "pytest"


def test_configure_error_tracking_initializes_sentry(monkeypatch):
    monkeypatch.setenv("ERROR_TRACKING_DSN", "https://public@example.ingest.sentry.io/1")
    monkeypatch.setenv("ERROR_TRACKING_ENVIRONMENT", "staging")
    monkeypatch.setenv("ERROR_TRACKING_RELEASE", "vetmanager-mcp@test")
    monkeypatch.setenv("ERROR_TRACKING_TRACES_SAMPLE_RATE", "0.25")

    with patch.object(error_tracking.sentry_sdk, "init") as init_mock:
        configured = error_tracking.configure_error_tracking()

    assert configured is True
    kwargs = init_mock.call_args.kwargs
    assert kwargs["dsn"] == "https://public@example.ingest.sentry.io/1"
    assert kwargs["environment"] == "staging"
    assert kwargs["release"] == "vetmanager-mcp@test"
    assert kwargs["send_default_pii"] is False
    assert kwargs["traces_sample_rate"] == 0.25
    assert kwargs["before_send"] is error_tracking._sanitize_event
    assert len(kwargs["integrations"]) == 1
    assert type(kwargs["integrations"][0]).__name__ == "StarletteIntegration"
    error_tracking._configured = False

"""Regression coverage for optional error tracking bootstrap."""

from unittest.mock import patch

import error_tracking


def test_configure_error_tracking_noops_without_dsn(monkeypatch):
    monkeypatch.delenv("ERROR_TRACKING_DSN", raising=False)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    assert error_tracking.configure_error_tracking() is False


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

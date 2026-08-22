"""Regression coverage for optional error tracking bootstrap."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import error_tracking
import pytest
from fastmcp.exceptions import ToolError

from exceptions import VetmanagerError
from filters import FilterPropertyValidationError
from tool_error_tracking import ToolErrorTrackingMiddleware


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
    assert "request" not in sanitized
    assert sanitized["tags"]["clinic_domain"] == "clinic.example"


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


@pytest.mark.asyncio
async def test_tool_failure_middleware_captures_one_safe_semantic_event(monkeypatch):
    middleware = ToolErrorTrackingMiddleware()
    domain_error = VetmanagerError("upstream failed", status_code=503)
    tool_error = ToolError("tool failed")
    tool_error.__cause__ = domain_error
    credentials = SimpleNamespace(account_id=42)

    async def fail(_context):
        raise tool_error

    with (
        patch("tool_error_tracking.get_current_runtime_credentials", return_value=credentials),
        patch("tool_error_tracking.capture_tool_failure") as capture,
    ):
        with pytest.raises(ToolError) as raised:
            await middleware.on_call_tool(SimpleNamespace(message=SimpleNamespace(name="get_payments")), fail)

    assert raised.value is tool_error
    assert getattr(tool_error, "_vetmanager_mcp_error_tracking_handled") is True
    capture.assert_called_once_with(tool_error, tool_name="get_payments", account_id=42)


@pytest.mark.asyncio
async def test_filter_property_rejection_is_marked_but_not_captured():
    middleware = ToolErrorTrackingMiddleware()
    filter_error = FilterPropertyValidationError("Unknown filter property 'close_date'.")
    tool_error = ToolError("tool failed")
    tool_error.__cause__ = filter_error

    async def fail(_context):
        raise tool_error

    with patch("tool_error_tracking.capture_tool_failure") as capture:
        with pytest.raises(ToolError):
            await middleware.on_call_tool(SimpleNamespace(message=SimpleNamespace(name="get_payments")), fail)

    capture.assert_not_called()
    assert getattr(tool_error, "_vetmanager_mcp_error_tracking_handled") is True


@pytest.mark.asyncio
async def test_tracking_context_lookup_failure_keeps_original_tool_error():
    middleware = ToolErrorTrackingMiddleware()
    tool_error = ToolError("tool failed")

    async def fail(_context):
        raise tool_error

    with (
        patch("tool_error_tracking.get_current_runtime_credentials", side_effect=RuntimeError("no context")),
        patch("tool_error_tracking.capture_tool_failure") as capture,
    ):
        with pytest.raises(ToolError) as raised:
            await middleware.on_call_tool(SimpleNamespace(message=SimpleNamespace(name="get_payments")), fail)

    assert raised.value is tool_error
    capture.assert_called_once_with(tool_error, tool_name="get_payments", account_id=None)


def test_capture_tool_failure_sets_semantic_tags_transaction_and_status(monkeypatch):
    scope = MagicMock()
    scope_context = MagicMock()
    scope_context.__enter__.return_value = scope
    domain_error = VetmanagerError("upstream failed", status_code=502)
    tool_error = ToolError("tool failed")
    tool_error.__cause__ = domain_error
    monkeypatch.setattr(error_tracking, "_configured", True)
    monkeypatch.setattr(error_tracking.sentry_sdk, "is_initialized", lambda: True)

    with (
        patch.object(error_tracking.sentry_sdk, "push_scope", return_value=scope_context),
        patch.object(error_tracking.sentry_sdk, "capture_exception") as capture,
    ):
        error_tracking.capture_tool_failure(tool_error, tool_name="get_payments", account_id=42)

    scope.set_tag.assert_any_call("mcp_tool_failure_capture", "manual")
    scope.set_tag.assert_any_call("tool", "get_payments")
    scope.set_tag.assert_any_call("account_id", "42")
    scope.set_tag.assert_any_call("upstream_status", "502")
    scope.set_transaction_name.assert_called_once_with("get_payments")
    capture.assert_called_once_with(tool_error)


def test_sanitizer_drops_only_marked_automatic_tool_error_and_keeps_manual_event():
    tool_error = ToolError("tool failed")
    error_tracking.mark_tool_error_as_handled(tool_error)
    hint = {"exc_info": (ToolError, tool_error, None)}

    assert error_tracking._sanitize_event({"tags": {}}, hint) is None
    manual = error_tracking._sanitize_event(
        {
            "tags": {"mcp_tool_failure_capture": "manual", "tool": "get_payments"},
            "request": {"headers": {"Authorization": "secret"}, "data": {"filter": "private"}},
            "extra": {"api_key": "secret"},
            "breadcrumbs": {"values": [{"data": {"token": "secret"}}]},
        },
        hint,
    )

    assert manual is not None
    assert manual["tags"]["tool"] == "get_payments"
    for key in ("request", "extra", "breadcrumbs", "contexts", "user"):
        assert key not in manual


def test_sanitizer_marker_lookup_uses_explicit_cause_and_missing_exc_info():
    marked = RuntimeError("marked")
    error_tracking.mark_tool_error_as_handled(marked)
    wrapped = RuntimeError("wrapped")
    wrapped.__cause__ = marked
    unrelated = RuntimeError("unrelated")
    unrelated.__context__ = marked

    assert error_tracking._sanitize_event({"tags": {}}, {"exc_info": (RuntimeError, wrapped, None)}) is None
    assert error_tracking._sanitize_event({"tags": {}}, {"exc_info": (RuntimeError, unrelated, None)}) == {"tags": {}}
    assert error_tracking._sanitize_event({"tags": {}}, {}) == {"tags": {}}


def test_resolve_release_canonicalizes_bare_prefixed_and_empty_values(monkeypatch):
    monkeypatch.setenv("ERROR_TRACKING_RELEASE", "abc123")
    assert error_tracking._resolve_release() == "vetmanager-mcp@abc123"
    monkeypatch.setenv("ERROR_TRACKING_RELEASE", "vetmanager-mcp@abc123")
    assert error_tracking._resolve_release() == "vetmanager-mcp@abc123"
    monkeypatch.setenv("ERROR_TRACKING_RELEASE", "")
    with patch("error_tracking.version", return_value="unknown"):
        assert error_tracking._resolve_release() == "vetmanager-mcp@unknown"

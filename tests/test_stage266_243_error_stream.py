"""Stages 266 and 243: the error stream must mean something.

266 — a caller's typo opened a Sentry issue even after stage 265.6 typed it,
because FastMCP logs the failure on its own boundary before our middleware sees
it, and the logging integration turns that record into an event. Measured live
on 28.08.2026: three deliberately wrong arguments opened PYTHON-10, PYTHON-11
and PYTHON-M, none of them through capture_tool_failure.

243 — every issue shows zero users affected. The tag has been there since stage
236; the field Sentry counts by has not. And the place that would set it is the
same place that strips it: the sanitizer drops `user` from our own events.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastmcp.exceptions import (
    PromptError,
    ResourceError,
    ToolError,
    ValidationError as SchemaValidationError,
)

import error_tracking
from exceptions import ToolInputError
from tool_error_tracking import ToolErrorTrackingMiddleware


FASTMCP_TOOL_LOGGER = "fastmcp.server.server"


def _context():
    return SimpleNamespace(message=SimpleNamespace(name="get_payments"))


async def _raising(exc):
    async def _call(_context):
        raise exc

    return _call


# ── 266: the channel we close ────────────────────────────────────────────────


def test_the_logger_that_duplicated_everything_is_shut_off(monkeypatch):
    """FastMCP reports the failure itself, before and besides our own capture."""
    monkeypatch.setenv("ERROR_TRACKING_DSN", "https://public@example.ingest.sentry.io/1")

    with patch.object(error_tracking.sentry_sdk, "init"):
        with patch.object(error_tracking, "ignore_logger") as ignored:
            error_tracking.configure_error_tracking()

    error_tracking._configured = False
    ignored.assert_called_once_with(FASTMCP_TOOL_LOGGER)


# ── 266: what we must not lose along with it ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        ToolError("Upstream API error (HTTP 500)."),
        ResourceError("resource is broken"),
        PromptError("prompt is broken"),
    ],
    ids=["tool", "resource", "prompt"],
)
async def test_a_failure_the_logger_used_to_report_alone_is_still_captured(exc):
    """Our middleware caught ToolError only, so these arrived through the logger.

    Closing that channel without widening the middleware would blind us to a
    whole class of failures instead of to the noise.
    """
    middleware = ToolErrorTrackingMiddleware()

    with patch("tool_error_tracking.capture_tool_failure") as capture:
        with pytest.raises(type(exc)):
            await middleware.on_call_tool(_context(), await _raising(exc))

    capture.assert_called_once()


@pytest.mark.asyncio
async def test_arguments_that_do_not_match_the_schema_are_not_a_defect():
    """FastMCP's own ValidationError is the caller's typo one level earlier.

    It produces no Sentry event today — FastMCP logs it as a warning — and
    widening the middleware must not quietly give it one.
    """
    middleware = ToolErrorTrackingMiddleware()
    schema_error = SchemaValidationError("clinic_id: expected integer")

    with patch("tool_error_tracking.capture_tool_failure") as capture:
        with pytest.raises(SchemaValidationError):
            await middleware.on_call_tool(_context(), await _raising(schema_error))

    capture.assert_not_called()


@pytest.mark.asyncio
async def test_the_callers_own_mistake_stays_uncaptured():
    middleware = ToolErrorTrackingMiddleware()

    with patch("tool_error_tracking.capture_tool_failure") as capture:
        with pytest.raises(ToolInputError):
            await middleware.on_call_tool(
                _context(), await _raising(ToolInputError("clinic_id must be positive.")),
            )

    capture.assert_not_called()


# ── 243: the field Sentry counts by ──────────────────────────────────────────


def _manual_event(**tags):
    return {"tags": {"mcp_tool_failure_capture": "manual", **tags}}


def test_the_affected_account_is_rebuilt_from_the_tag_we_already_verified():
    event = error_tracking._sanitize_event(_manual_event(account_id="42"), None)

    assert event is not None
    assert event["user"] == {"id": "42"}


def test_a_handled_connection_failure_counts_its_account_too():
    event = error_tracking._sanitize_event(
        {"tags": {"handled_connection_failure": "true", "account_id": "7"}}, None,
    )

    assert event is not None
    assert event["user"] == {"id": "7"}


def test_nothing_the_event_carried_survives_into_the_user():
    """Rebuilt, not preserved: whatever Starlette attached is gone first."""
    event = error_tracking._sanitize_event(
        {
            "tags": {"mcp_tool_failure_capture": "manual", "account_id": "42"},
            "user": {"id": "someone-else", "email": "vet@example.com", "ip_address": "1.2.3.4"},
        },
        None,
    )

    assert event["user"] == {"id": "42"}


@pytest.mark.parametrize("account_id", ["", "not-a-number", "12x", " 42", None])
def test_an_account_tag_we_cannot_trust_produces_no_user(account_id):
    tags = {"mcp_tool_failure_capture": "manual"}
    if account_id is not None:
        tags["account_id"] = account_id

    event = error_tracking._sanitize_event({"tags": tags}, None)

    assert "user" not in event


def test_an_ordinary_event_is_not_given_a_user():
    """Only our own two kinds of event are rebuilt; the rest keep their shape."""
    event = error_tracking._sanitize_event({"tags": {"account_id": "42"}}, None)

    assert "user" not in event


# ── 243: the paths we do not raise ourselves ─────────────────────────────────


def test_an_unhandled_failure_still_knows_whose_call_it_was(monkeypatch):
    """capture_tool_failure tags its own events. Nothing tags the others."""
    monkeypatch.setattr(error_tracking, "_configured", True)
    with patch.object(error_tracking.sentry_sdk, "is_initialized", return_value=True):
        with patch.object(error_tracking.sentry_sdk, "set_user") as set_user:
            error_tracking.set_affected_account(42)

    set_user.assert_called_once_with({"id": "42"})


def test_an_unauthenticated_call_names_nobody(monkeypatch):
    monkeypatch.setattr(error_tracking, "_configured", True)
    with patch.object(error_tracking.sentry_sdk, "is_initialized", return_value=True):
        with patch.object(error_tracking.sentry_sdk, "set_user") as set_user:
            error_tracking.set_affected_account(None)

    set_user.assert_not_called()


def test_naming_the_account_never_breaks_the_call(monkeypatch):
    monkeypatch.setattr(error_tracking, "_configured", True)
    with patch.object(error_tracking.sentry_sdk, "is_initialized", return_value=True):
        with patch.object(error_tracking.sentry_sdk, "set_user", side_effect=RuntimeError("boom")):
            error_tracking.set_affected_account(42)  # must not raise

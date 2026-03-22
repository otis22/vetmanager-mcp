"""Contract tests for structured logging baseline."""

from __future__ import annotations

import json
import logging

from structured_logging import (
    DEFAULT_LOG_FORMAT,
    JsonLogFormatter,
    RequestContextLogFilter,
    STRUCTURED_LOG_RECORD_FIELDS,
    TextLogFormatter,
    build_log_formatter,
    get_log_format,
)


def test_get_log_format_defaults_to_text(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    assert get_log_format() == DEFAULT_LOG_FORMAT


def test_get_log_format_rejects_unknown_values(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "xml")

    assert get_log_format() == DEFAULT_LOG_FORMAT


def test_build_log_formatter_supports_json(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")

    assert isinstance(build_log_formatter(), JsonLogFormatter)


def test_json_formatter_emits_stable_core_fields():
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="vetmanager.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=12,
        msg="structured message",
        args=(),
        exc_info=None,
    )
    record.account_id = 7
    payload = json.loads(formatter.format(record))

    for field in STRUCTURED_LOG_RECORD_FIELDS:
        assert field in payload
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "vetmanager.test"
    assert payload["message"] == "structured message"
    assert payload["account_id"] == 7


def test_text_formatter_preserves_core_message_and_extras():
    formatter = TextLogFormatter()
    record = logging.LogRecord(
        name="vetmanager.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=18,
        msg="text message",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-1"

    rendered = formatter.format(record)

    assert "[INFO]" in rendered
    assert "vetmanager.test" in rendered
    assert "text message" in rendered
    assert "request_id=req-1" in rendered


def test_request_context_log_filter_attaches_request_fields(monkeypatch):
    record = logging.LogRecord(
        name="vetmanager.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=30,
        msg="with context",
        args=(),
        exc_info=None,
    )

    monkeypatch.setattr(
        "structured_logging.get_current_request_context",
        lambda: {"request_id": "req-1", "correlation_id": "corr-1"},
    )

    RequestContextLogFilter().filter(record)

    assert record.request_id == "req-1"
    assert record.correlation_id == "corr-1"

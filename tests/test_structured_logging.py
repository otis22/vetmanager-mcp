"""Contract tests for structured logging baseline."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from structured_logging import (
    DEFAULT_LOG_FORMAT,
    JsonLogFormatter,
    RequestContextLogFilter,
    STRUCTURED_LOG_RECORD_FIELDS,
    TextLogFormatter,
    PersistentRotatingFileHandler,
    build_log_formatter,
    get_log_format,
)
from privacy_utils import mask_ip_to_network


def test_structured_log_ip_values_are_masked_to_network():
    assert mask_ip_to_network("203.0.113.42") == "203.0.113.0"
    assert mask_ip_to_network("2001:db8:1:2::42") == "2001:db8:1:2::"


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


def test_persistent_log_handler_rotates_and_bounds_files(tmp_path, monkeypatch):
    monkeypatch.setattr("structured_logging.PERSISTENT_LOG_MAX_BYTES", 1)
    monkeypatch.setattr("structured_logging.PERSISTENT_LOG_MAX_FILES", 2)
    handler = PersistentRotatingFileHandler(str(tmp_path))
    handler.setFormatter(logging.Formatter("%(message)s"))

    for message in ("one", "two", "three"):
        handler.emit(logging.makeLogRecord({"msg": message, "args": ()}))

    files = sorted(Path(tmp_path).glob("runtime-*.log"))
    assert len(files) == 2
    assert [path.read_text().strip() for path in files] == ["two", "three"]


def test_mcp_compose_contract_enables_persistent_and_error_tracking_envs():
    compose = Path("docker-compose.yml").read_text()

    for value in (
        "PERSISTENT_LOG_PATH: /var/log/vetmanager-mcp",
        "ERROR_TRACKING_DSN: ${ERROR_TRACKING_DSN:-}",
        "ERROR_TRACKING_ENVIRONMENT: ${ERROR_TRACKING_ENVIRONMENT:-production}",
        "ERROR_TRACKING_TRACES_SAMPLE_RATE: ${ERROR_TRACKING_TRACES_SAMPLE_RATE:-0}",
        "mcp-logs:/var/log/vetmanager-mcp",
        "driver: json-file",
        "max-size: 10m",
        'max-file: "3"',
    ):
        assert value in compose

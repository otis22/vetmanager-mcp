"""Structured logging setup shared by runtime, web, and future observability hooks."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from request_context import get_current_request_context

DEFAULT_LOG_FORMAT = "text"
SUPPORTED_LOG_FORMATS = {"json", "text"}
STRUCTURED_LOG_RECORD_FIELDS = (
    "timestamp",
    "level",
    "logger",
    "message",
)
_RESERVED_LOG_RECORD_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def get_log_format() -> str:
    """Return normalized log format contract for current runtime."""
    value = (os.environ.get("LOG_FORMAT") or DEFAULT_LOG_FORMAT).strip().lower()
    if value not in SUPPORTED_LOG_FORMATS:
        return DEFAULT_LOG_FORMAT
    return value


def _record_timestamp(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_LOG_RECORD_ATTRS or key.startswith("_"):
            continue
        extra[key] = value
    return extra


class JsonLogFormatter(logging.Formatter):
    """Render log records as stable one-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _record_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        payload.update(_extra_fields(record))
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


class TextLogFormatter(logging.Formatter):
    """Render logs in text form while keeping the same core event fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": _record_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extras = _extra_fields(record)
        extras_text = ""
        if extras:
            serialized = " ".join(f"{key}={value}" for key, value in sorted(extras.items()))
            extras_text = f" {serialized}"
        base = (
            f"{payload['timestamp']} [{payload['level']}] "
            f"{payload['logger']}: {payload['message']}{extras_text}"
        )
        if record.exc_info:
            return f"{base}\n{self.formatException(record.exc_info)}"
        return base


class RequestContextLogFilter(logging.Filter):
    """Attach request-scoped ids to log records when available."""

    def filter(self, record: logging.LogRecord) -> bool:
        context = get_current_request_context()
        for key, value in context.items():
            if not getattr(record, key, None):
                setattr(record, key, value)
        return True


def build_log_formatter(*, log_format: str | None = None) -> logging.Formatter:
    """Return formatter matching the current structured logging contract."""
    effective_format = log_format or get_log_format()
    if effective_format == "json":
        return JsonLogFormatter()
    return TextLogFormatter()


_HANDLER_MARKER = "_vm_structured_logging_handler"


def _is_our_handler(handler: logging.Handler) -> bool:
    return getattr(handler, _HANDLER_MARKER, False) is True


def configure_logging() -> None:
    """Initialize root logging with the configured structured formatter.

    Stage 101.8: never reset root handlers (`basicConfig(force=True)` was
    clobbering pytest's `caplog` handler — tests then needed `_StubLogger`
    workarounds to assert on structured log records). Instead, we add our
    own stream handler, tagged with a marker attribute, alongside any
    pre-existing handlers so test fixtures and third-party bootstrap keep
    working.

    Idempotent: checked by scanning root handlers for our marker. Using
    a handler-based check (rather than a module-level boolean) means that
    if some later code clears root handlers (`basicConfig(force=True)`,
    `dictConfig(...)`, manual `removeHandler`), the next call will correctly
    re-install ours. Avoids double-install when the host process pre-set
    its own handler — we only install ours if it isn't already there.
    """
    root = logging.getLogger()
    level = (os.environ.get("LOG_LEVEL") or "INFO").strip().upper()
    root.setLevel(level)

    if any(_is_our_handler(h) for h in root.handlers):
        return

    formatter = build_log_formatter()
    context_filter = RequestContextLogFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    setattr(stream_handler, _HANDLER_MARKER, True)
    root.addHandler(stream_handler)

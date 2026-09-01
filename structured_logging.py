"""Structured logging setup shared by runtime, web, and future observability hooks."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

from request_context import get_current_request_context
from privacy_utils import mask_ip_to_network, scrub_report_export_path

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
        extra[key] = (
            mask_ip_to_network(value) if key.lower() in {
                "client_ip", "x-forwarded-for", "x-real-ip", "remote_addr", "ip_address"
            } else value
        )
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
PERSISTENT_LOG_MAX_BYTES = 10 * 1024 * 1024
PERSISTENT_LOG_MAX_FILES = 14


class PersistentRotatingFileHandler(logging.Handler):
    """Bounded UTC-day log files in a Docker named volume."""

    def __init__(self, directory: str) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.directory.is_dir():
            raise RuntimeError(f"Persistent log path is not a directory: {directory}")
        probe_path = self.directory / f".write-probe-{os.getpid()}"
        with probe_path.open("x", encoding="utf-8"):
            pass
        probe_path.unlink()
        self.current_path: Path | None = None

    def _next_path(self) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        existing = sorted(self.directory.glob(f"runtime-{day}-*.log"))
        index = len(existing) + 1
        return self.directory / f"runtime-{day}-{index:03d}.log"

    def _path_for_record(self, rendered: str) -> Path:
        encoded_size = len((rendered + "\n").encode("utf-8"))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if (
            self.current_path is None
            or f"runtime-{today}-" not in self.current_path.name
            or (self.current_path.exists() and self.current_path.stat().st_size + encoded_size > PERSISTENT_LOG_MAX_BYTES)
        ):
            self.current_path = self._next_path()
        return self.current_path

    def _prune(self) -> None:
        files = sorted(self.directory.glob("runtime-????-??-??-*.log"))
        oldest_day = (datetime.now(timezone.utc) - timedelta(days=13)).date()
        for path in files:
            file_day = datetime.strptime(path.name[8:18], "%Y-%m-%d").date()
            if file_day < oldest_day:
                path.unlink(missing_ok=True)
        files = sorted(self.directory.glob("runtime-????-??-??-*.log"))
        for path in files[:-PERSISTENT_LOG_MAX_FILES]:
            path.unlink(missing_ok=True)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            path = self._path_for_record(self.format(record))
            with path.open("a", encoding="utf-8") as stream:
                stream.write(self.format(record) + "\n")
            self._prune()
        except Exception:
            self.handleError(record)


class ReportExportPathFilter(logging.Filter):
    """Keep the key to an export file out of the access log.

    Stage 276: `uvicorn` is started with `access_log=True` and
    `PERSISTENT_LOG_PATH` writes that log to disk, so the signed download path
    — which is the whole authorization for the file — would be persisted in
    plain text. Access records carry the path as an argument, not in the
    message, so the argument is what gets replaced.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            replaced = scrub_report_export_path(args[2])
            if replaced != args[2]:
                record.args = args[:2] + (replaced,) + args[3:]
        if isinstance(record.msg, str):
            record.msg = scrub_report_export_path(record.msg)
        return True


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

    # Stage 278: `httpx` logs every request line at INFO, address included.
    # The export download goes to a public CDN link that serves the raw,
    # uncleaned file to anyone holding it — and production runs at INFO with a
    # persistent log on disk. Our own instrumentation already records endpoint,
    # method, status and duration, so nothing is lost by silencing the library.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, ReportExportPathFilter) for item in access_logger.filters):
        access_logger.addFilter(ReportExportPathFilter())

    if any(_is_our_handler(h) for h in root.handlers):
        return

    formatter = build_log_formatter()
    context_filter = RequestContextLogFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    setattr(stream_handler, _HANDLER_MARKER, True)
    root.addHandler(stream_handler)

    persistent_log_path = (os.environ.get("PERSISTENT_LOG_PATH") or "").strip()
    if persistent_log_path:
        persistent_handler = PersistentRotatingFileHandler(persistent_log_path)
        persistent_handler.setFormatter(formatter)
        persistent_handler.addFilter(context_filter)
        setattr(persistent_handler, _HANDLER_MARKER, True)
        root.addHandler(persistent_handler)

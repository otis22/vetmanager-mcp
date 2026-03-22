"""Contract tests for runtime/audit/security logger taxonomy."""

from __future__ import annotations

import logging

from observability_logging import (
    AUDIT_LOGGER,
    EVENT_CATEGORY_AUDIT,
    EVENT_CATEGORY_RUNTIME,
    EVENT_CATEGORY_SECURITY,
    RUNTIME_LOGGER,
    SECURITY_LOGGER,
)


def test_category_loggers_use_stable_names_and_categories():
    assert RUNTIME_LOGGER.logger.name == "vetmanager.runtime"
    assert AUDIT_LOGGER.logger.name == "vetmanager.audit"
    assert SECURITY_LOGGER.logger.name == "vetmanager.security"
    assert RUNTIME_LOGGER.extra["event_category"] == EVENT_CATEGORY_RUNTIME
    assert AUDIT_LOGGER.extra["event_category"] == EVENT_CATEGORY_AUDIT
    assert SECURITY_LOGGER.extra["event_category"] == EVENT_CATEGORY_SECURITY


def test_category_logger_adapter_merges_event_fields():
    record = logging.LogRecord(
        name="vetmanager.runtime",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg="runtime event",
        args=(),
        exc_info=None,
    )
    _, kwargs = RUNTIME_LOGGER.process(
        "runtime event",
        {"extra": {"event_name": "billing_host_resolved", "domain": "clinic-a"}},
    )

    for key, value in kwargs["extra"].items():
        setattr(record, key, value)

    assert record.event_category == EVENT_CATEGORY_RUNTIME
    assert record.event_name == "billing_host_resolved"
    assert record.domain == "clinic-a"

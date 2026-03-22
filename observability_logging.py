"""Named logger taxonomy for runtime, audit, and security event streams."""

from __future__ import annotations

import logging
from typing import Any

EVENT_CATEGORY_RUNTIME = "runtime"
EVENT_CATEGORY_AUDIT = "audit"
EVENT_CATEGORY_SECURITY = "security"


class CategoryLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that preserves category metadata and merges per-call extras."""

    def process(self, msg: str, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        merged_extra = dict(self.extra)
        merged_extra.update(kwargs.get("extra", {}))
        kwargs["extra"] = merged_extra
        return msg, kwargs


def get_category_logger(category: str) -> CategoryLoggerAdapter:
    """Return stable category logger adapter for structured observability events."""
    return CategoryLoggerAdapter(
        logging.getLogger(f"vetmanager.{category}"),
        {"event_category": category},
    )


RUNTIME_LOGGER = get_category_logger(EVENT_CATEGORY_RUNTIME)
AUDIT_LOGGER = get_category_logger(EVENT_CATEGORY_AUDIT)
SECURITY_LOGGER = get_category_logger(EVENT_CATEGORY_SECURITY)

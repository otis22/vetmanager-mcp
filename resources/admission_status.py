"""Admission-status enum constants (stage 106.3).

Moved from `tools.admission` to the `resources/` layer so resource-level
modules (client_profile, etc.) can import without reaching up into the
MCP-tool layer. Tools import from here too.

Values come from Vetmanager migration
`m190218_081130_add_admission_not_confirmed_status.php` and represent
admissions that are actively scheduled or in progress — used for
filtering "upcoming visits" and similar aggregator queries.
"""

from __future__ import annotations

ACTIVE_ADMISSION_STATUSES: tuple[str, ...] = (
    "save",
    "directed",
    "accepted",
    "in_treatment",
    "delayed",
    "not_confirmed",
)

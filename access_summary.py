"""Stage 273: what an access preset gives, in words a clinic owner can check.

The account page used to offer seven words — "Front desk", "Analytics" — and
nothing else, so the only way to find out what a key could do was to count the
tools it advertised. That is exactly what a reader of the service did before
concluding it hands out full access to the clinic database.

Listing tools would not help either: Analytics reaches 97 of them. What a
person actually needs is the shape of the access — which parts of the clinic,
and whether the assistant can only look or also change and delete.
"""

from __future__ import annotations

from dataclasses import dataclass

from token_scopes import (
    SCOPE_ADMISSIONS_READ,
    SCOPE_ADMISSIONS_WRITE,
    SCOPE_ANALYTICS_READ,
    SCOPE_ANALYTICS_WRITE,
    SCOPE_CLIENTS_READ,
    SCOPE_CLIENTS_WRITE,
    SCOPE_FINANCE_READ,
    SCOPE_FINANCE_WRITE,
    SCOPE_INVENTORY_READ,
    SCOPE_INVENTORY_WRITE,
    SCOPE_MEDICAL_CARDS_READ,
    SCOPE_MEDICAL_CARDS_WRITE,
    SCOPE_MESSAGING_READ,
    SCOPE_MESSAGING_WRITE,
    SCOPE_PETS_READ,
    SCOPE_PETS_WRITE,
    SCOPE_RECORDS_DELETE,
    SCOPE_REFERENCE_READ,
    SCOPE_REPORT_AI_WRITE,
    SCOPE_SCHEDULE_WRITE,
    SCOPE_USERS_READ,
    SCOPE_USERS_WRITE,
)


@dataclass(frozen=True)
class AccessArea:
    """One part of the clinic, and the rights that open it."""

    label: str
    read_scope: str | None = None
    write_scope: str | None = None


# Named by what the right actually opens, not by the scope's own name:
# reports live on `report_ai.write`, and the schedule got a name of its own in
# stage 310 — until then it was hiding under `analytics.write`.
ACCESS_AREAS: tuple[AccessArea, ...] = (
    AccessArea("клиенты", SCOPE_CLIENTS_READ, SCOPE_CLIENTS_WRITE),
    AccessArea("питомцы", SCOPE_PETS_READ, SCOPE_PETS_WRITE),
    AccessArea("приёмы", SCOPE_ADMISSIONS_READ, SCOPE_ADMISSIONS_WRITE),
    AccessArea("медкарты и госпитализация", SCOPE_MEDICAL_CARDS_READ, SCOPE_MEDICAL_CARDS_WRITE),
    AccessArea("финансы", SCOPE_FINANCE_READ, SCOPE_FINANCE_WRITE),
    AccessArea("склад", SCOPE_INVENTORY_READ, SCOPE_INVENTORY_WRITE),
    AccessArea("сотрудники", SCOPE_USERS_READ, SCOPE_USERS_WRITE),
    AccessArea("смены и статистика", SCOPE_ANALYTICS_READ, SCOPE_SCHEDULE_WRITE),
    AccessArea("справочники", SCOPE_REFERENCE_READ, None),
    AccessArea("рассылки", SCOPE_MESSAGING_READ, SCOPE_MESSAGING_WRITE),
    AccessArea("отчёты", None, SCOPE_REPORT_AI_WRITE),
)

# What the delete right actually removes. Pinned by a test against the tools
# that require it, so a third deleting tool cannot appear without this line
# being corrected.
DELETABLE_RECORDS = "клиенты и питомцы"

# Stage 310: the schedule right removes rows too. A shift has no deleted
# status, so `delete_timesheet` erases it — and a page that answered "нет"
# here would be making the exact promise stage 273 built this line to keep.
DELETABLE_SHIFTS = "смены графика"

# Stage 310: kept supported so manifests of keys issued earlier still parse,
# but no tool asks for it any more. Listed here because every right must be
# accounted for, and a right that opens nothing has no area on the screen.
STALE_SCOPES = frozenset({SCOPE_ANALYTICS_WRITE})

NOTHING = "нет"


def _areas(scopes: set[str], attribute: str) -> list[str]:
    return [
        area.label
        for area in ACCESS_AREAS
        if getattr(area, attribute) is not None and getattr(area, attribute) in scopes
    ]


def summarize_access(scopes) -> tuple[tuple[str, str], ...]:
    """Three lines describing what these rights allow.

    All three are always present. "Удаление: нет" is the point of the exercise:
    a preset that cannot delete should say so, because the reader's worry is
    precisely the thing that is not on the screen.
    """
    granted = set(scopes or ())
    reading = _areas(granted, "read_scope")
    changing = _areas(granted, "write_scope")
    removable = []
    if SCOPE_RECORDS_DELETE in granted:
        removable.append(DELETABLE_RECORDS)
    if SCOPE_SCHEDULE_WRITE in granted:
        removable.append(DELETABLE_SHIFTS)
    deleting = ", ".join(removable) or NOTHING
    return (
        ("Чтение", ", ".join(reading) or NOTHING),
        ("Изменение", ", ".join(changing) or NOTHING),
        ("Удаление", deleting),
    )

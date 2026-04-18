"""Cache TTL tiers and entity → TTL routing.

Stage 103d: extracted from `vetmanager_client.py`. Trivial constants plus
one helper that turns a request path like `/rest/api/client/5` into the
entity key (`client`) used for cache-tag invalidation.
"""

from __future__ import annotations

# Default cache TTL for stable reference data (breeds, cities, goods, etc.).
CACHE_TTL_SECONDS = 900.0

# Short TTL for frequently-updated entities: admissions, medical cards,
# invoices, clients. Keeps data fresh while still reducing redundant API
# calls within a single session.
CACHE_TTL_SHORT_SECONDS = 60.0

# Entities that change often and should use the short TTL.
SHORT_TTL_ENTITIES = frozenset({
    "admission",
    "medicalcard",
    "invoice",
    "client",
    "pet",
    "payment",
})


def entity_from_path(path: str) -> str:
    """Extract the entity segment from a Vetmanager REST path.

    Examples:
        /rest/api/client/5         → "client"
        /rest/api/MedicalCards     → "medicalcards"  (lowercased)
        /rest/api/                 → "unknown"
        /something-else            → "unknown"
    """
    normalized = path.split("?", 1)[0].strip("/")
    parts = normalized.split("/")
    if len(parts) >= 3 and parts[0].lower() == "rest" and parts[1].lower() == "api":
        return parts[2].lower()
    return "unknown"


def ttl_for_entity(entity_name: str) -> float:
    """Return the cache TTL (seconds) for a given entity."""
    if entity_name in SHORT_TTL_ENTITIES:
        return CACHE_TTL_SHORT_SECONDS
    return CACHE_TTL_SECONDS

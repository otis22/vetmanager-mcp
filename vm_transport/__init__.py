"""Transport layer for Vetmanager REST API client.

Stage 103d: split of `vetmanager_client.py` into focused concerns.
`VetmanagerClient` (the orchestrator class) remains in `vetmanager_client`
and composes the primitives exported here.

Submodules:
- `retry`        — backoff math, Retry-After parsing, retry constants
- `cache_policy` — TTL tiers and entity → TTL routing
- `pool`         — shared `httpx.AsyncClient` keyed per running event loop
- `breaker`      — per-domain circuit breaker state and transitions
"""

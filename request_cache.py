"""In-memory tagged cache for Vetmanager GET requests."""

from __future__ import annotations

import asyncio
import copy
import os
import socket
import time
from dataclasses import dataclass, field
from typing import Any

from observability_logging import RUNTIME_LOGGER
import shared_metric_counters


_DEFAULT_MAX_ENTRIES = 2048


def _slot_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _shared_cache_event(family: str) -> None:
    try:
        backend = shared_metric_counters.get_backend()
        if backend is not None:
            def deliver() -> None:
                try:
                    backend.increment(family, "")
                except Exception as exc:
                    RUNTIME_LOGGER.warning("Shared cache metric event lost", extra={
                        "event_name": "shared_metric_event_lost", "metric_family": family,
                        "error_class": type(exc).__name__,
                    })

            shared_metric_counters.dispatch(deliver)
    except Exception as exc:
        RUNTIME_LOGGER.warning("Shared cache metric event lost", extra={
            "event_name": "shared_metric_event_lost", "metric_family": family,
            "error_class": type(exc).__name__,
        })


def _shared_cache_gauge(count: int) -> None:
    try:
        backend = shared_metric_counters.get_backend()
        if backend is not None:
            slot = _slot_identity()

            def deliver() -> None:
                try:
                    backend.publish_cache_entries(slot, count)
                except Exception as exc:
                    RUNTIME_LOGGER.warning("Shared cache gauge unavailable", extra={
                        "event_name": "shared_metric_event_lost", "metric_family": "cache_entries",
                        "error_class": type(exc).__name__,
                    })

            shared_metric_counters.dispatch(deliver)
    except Exception as exc:
        RUNTIME_LOGGER.warning("Shared cache gauge unavailable", extra={
            "event_name": "shared_metric_event_lost", "metric_family": "cache_entries",
            "error_class": type(exc).__name__,
        })


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    tags: tuple[str, ...]
    last_accessed: float = field(default_factory=time.monotonic)


class CacheMetrics:
    """Simple counters for cache observability."""

    __slots__ = ("hits", "misses", "invalidations", "evictions")

    def __init__(self) -> None:
        self.hits: int = 0
        self.misses: int = 0
        self.invalidations: int = 0
        self.evictions: int = 0


class InMemoryTaggedCache:
    """Process-local tagged cache with TTL, LRU eviction, and metrics."""

    def __init__(self, *, max_entries: int = _DEFAULT_MAX_ENTRIES) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._tag_index: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._max_entries = max_entries
        self.metrics = CacheMetrics()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            self._cleanup_expired_unlocked()
            entry = self._entries.get(key)
            if entry is None:
                self.metrics.misses += 1
                _shared_cache_event("cache_misses_total")
                return None
            entry.last_accessed = time.monotonic()
            self.metrics.hits += 1
            _shared_cache_event("cache_hits_total")
            return copy.deepcopy(entry.value)

    async def set(self, key: str, value: Any, ttl_seconds: float, tags: tuple[str, ...]) -> None:
        async with self._lock:
            self._cleanup_expired_unlocked()

            # Remove old entry's tag associations if overwriting.
            if key in self._entries:
                old_tags = self._entries[key].tags
                for tag in old_tags:
                    keys = self._tag_index.get(tag)
                    if keys is not None:
                        keys.discard(key)
                        if not keys:
                            self._tag_index.pop(tag, None)

            # LRU eviction if at capacity.
            while len(self._entries) >= self._max_entries:
                self._evict_lru_unlocked()

            expires_at = time.monotonic() + ttl_seconds
            self._entries[key] = CacheEntry(
                value=copy.deepcopy(value),
                expires_at=expires_at,
                tags=tags,
                last_accessed=time.monotonic(),
            )
            for tag in tags:
                self._tag_index.setdefault(tag, set()).add(key)
            _shared_cache_gauge(len(self._entries))

    async def invalidate_tag(self, tag: str) -> None:
        async with self._lock:
            keys = self._tag_index.pop(tag, set())
            self.metrics.invalidations += 1
            _shared_cache_event("cache_invalidations_total")
            for key in keys:
                entry = self._entries.pop(key, None)
                if entry is None:
                    continue
                for entry_tag in entry.tags:
                    if entry_tag == tag:
                        continue
                    tag_keys = self._tag_index.get(entry_tag)
                    if tag_keys is not None:
                        tag_keys.discard(key)
                        if not tag_keys:
                            self._tag_index.pop(entry_tag, None)
            _shared_cache_gauge(len(self._entries))

    async def refresh_shared_gauge(self) -> None:
        """Renew the slot lease and expire stale local entries even when idle."""
        async with self._lock:
            self._cleanup_expired_unlocked()
            _shared_cache_gauge(len(self._entries))

    @property
    def size(self) -> int:
        return len(self._entries)

    def _evict_lru_unlocked(self) -> None:
        if not self._entries:
            return
        lru_key = min(self._entries, key=lambda k: self._entries[k].last_accessed)
        entry = self._entries.pop(lru_key)
        self.metrics.evictions += 1
        _shared_cache_event("cache_evictions_total")
        for tag in entry.tags:
            tag_keys = self._tag_index.get(tag)
            if tag_keys is not None:
                tag_keys.discard(lru_key)
                if not tag_keys:
                    self._tag_index.pop(tag, None)

    def _cleanup_expired_unlocked(self) -> None:
        now = time.monotonic()
        expired_keys = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired_keys:
            entry = self._entries.pop(key, None)
            if entry is None:
                continue
            for tag in entry.tags:
                tag_keys = self._tag_index.get(tag)
                if tag_keys is not None:
                    tag_keys.discard(key)
                    if not tag_keys:
                        self._tag_index.pop(tag, None)


REQUEST_CACHE = InMemoryTaggedCache()

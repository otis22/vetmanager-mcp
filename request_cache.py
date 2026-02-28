"""In-memory tagged cache for Vetmanager GET requests."""

from __future__ import annotations

import asyncio
import copy
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    tags: tuple[str, ...]


class InMemoryTaggedCache:
    """Simple process-local tagged cache with TTL support."""

    def __init__(self) -> None:
        self._entries: dict[str, CacheEntry] = {}
        self._tag_index: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            self._cleanup_expired_unlocked()
            entry = self._entries.get(key)
            if entry is None:
                return None
            return copy.deepcopy(entry.value)

    async def set(self, key: str, value: Any, ttl_seconds: float, tags: tuple[str, ...]) -> None:
        async with self._lock:
            self._cleanup_expired_unlocked()
            if key in self._entries:
                old_tags = self._entries[key].tags
                for tag in old_tags:
                    keys = self._tag_index.get(tag)
                    if keys is not None:
                        keys.discard(key)
                        if not keys:
                            self._tag_index.pop(tag, None)

            expires_at = time.monotonic() + ttl_seconds
            self._entries[key] = CacheEntry(
                value=copy.deepcopy(value),
                expires_at=expires_at,
                tags=tags,
            )
            for tag in tags:
                self._tag_index.setdefault(tag, set()).add(key)

    async def invalidate_tag(self, tag: str) -> None:
        async with self._lock:
            keys = self._tag_index.pop(tag, set())
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

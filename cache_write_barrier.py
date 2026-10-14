"""PostgreSQL backed cache generations for writes across MCP slots."""

from __future__ import annotations

import hashlib
import hmac
import json

from sqlalchemy import select, text, update

from storage import get_session_factory
from storage_models import VetmanagerCacheBarrier
from web_auth import get_web_session_secret


def tag_hash(*, domain: str, account_id: int | None, entity: str) -> str:
    key = hmac.new(get_web_session_secret().encode(), b"vm-cache-tag-v1",
                   hashlib.sha256).digest()
    identity = json.dumps([domain, account_id, entity], separators=(",", ":")).encode()
    return hmac.new(key, identity, hashlib.sha256).hexdigest()


async def read_generation(tag: str) -> int | None:
    """Return None when a write is active; propagate PG errors to the caller."""
    async with get_session_factory()() as session:
        row = (await session.execute(select(
            VetmanagerCacheBarrier.generation, VetmanagerCacheBarrier.active_writes,
        ).where(VetmanagerCacheBarrier.tag_hash == tag))).one_or_none()
        if row is None:
            return 0
        return int(row.generation) if row.active_writes == 0 else None


async def begin_write(tag: str) -> None:
    """Commit the barrier before the caller sends anything to Vetmanager."""
    async with get_session_factory()() as session:
        async with session.begin():
            await session.execute(text(
                "INSERT INTO vetmanager_cache_barriers "
                "(tag_hash, generation, active_writes) VALUES (:tag, 0, 0) "
                "ON CONFLICT (tag_hash) DO NOTHING"), {"tag": tag})
            await session.execute(update(VetmanagerCacheBarrier).where(
                VetmanagerCacheBarrier.tag_hash == tag).values(
                    active_writes=VetmanagerCacheBarrier.active_writes + 1))


async def finish_write(tag: str) -> None:
    """Advance the generation; a failed commit leaves the durable fence up."""
    async with get_session_factory()() as session:
        async with session.begin():
            result = await session.execute(update(VetmanagerCacheBarrier).where(
                VetmanagerCacheBarrier.tag_hash == tag,
                VetmanagerCacheBarrier.active_writes > 0,
            ).values(
                generation=VetmanagerCacheBarrier.generation + 1,
                active_writes=VetmanagerCacheBarrier.active_writes - 1,
            ))
            if result.rowcount != 1:
                raise RuntimeError("Cache write barrier state is missing")

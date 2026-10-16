"""Local, privacy-filtered journal of Report AI intents and agent ratings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from agent_feedback_service import sanitize_text
from depersonalization import sanitize_report_value
from domain_validation import validate_domain
from exceptions import ToolInputError
from service_metrics import record_report_ai_rating
from storage import get_session_factory
from storage_models import ReportAiJobRating

RETENTION_DAYS = 180


def _identity(account_id: int | None, connection_id: int | None,
              domain: str, job_id: int) -> dict[str, int | str]:
    if (isinstance(account_id, bool) or not isinstance(account_id, int) or account_id <= 0
            or isinstance(connection_id, bool) or not isinstance(connection_id, int) or connection_id <= 0
            or isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0):
        raise ToolInputError("A registered Report AI job is required for rating.")
    return {"account_id": account_id, "connection_id": connection_id,
            "domain": validate_domain(domain), "job_id": job_id}


def _safe_free_text(value: str, *, limit: int) -> str:
    return sanitize_text(sanitize_report_value(value), limit=limit, required=True) or "[REDACTED]"


async def record_created_job(*, account_id: int, connection_id: int, domain: str,
                             job_id: int, intent_text: str, allow_new: bool = True) -> bool:
    """Register one upstream job without changing an earlier intent or rating."""
    key = _identity(account_id, connection_id, domain, job_id)
    async with get_session_factory()() as session:
        if not allow_new:
            existing = await session.scalar(
                select(ReportAiJobRating.id).filter_by(**key))
            return existing is not None
        safe_intent = _safe_free_text(intent_text, limit=20000)
        values = {**key, "intent_text": safe_intent}
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            statement = pg_insert(ReportAiJobRating).values(**values)
        elif dialect == "sqlite":
            statement = sqlite_insert(ReportAiJobRating).values(**values)
        else:
            raise RuntimeError("Report AI rating storage requires PostgreSQL or SQLite.")
        await session.execute(statement.on_conflict_do_nothing(
            index_elements=["account_id", "connection_id", "domain", "job_id"]))
        await session.commit()
    return True


async def rate_job(*, account_id: int, connection_id: int, domain: str,
                   job_id: int, score: int, comment: str | None = None) -> dict:
    """Replace this connection's rating for a job; keep its original intent."""
    key = _identity(account_id, connection_id, domain, job_id)
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 10:
        raise ToolInputError("score must be an integer from 1 to 10.")
    if comment is not None and not isinstance(comment, str):
        raise ToolInputError("comment must be text.")
    safe_comment = _safe_free_text(comment, limit=1000) if comment and comment.strip() else None
    rated_at = datetime.now(timezone.utc)
    async with get_session_factory()() as session:
        result = await session.execute(
            update(ReportAiJobRating).filter_by(**key).values(
                score=score, comment=safe_comment, rated_at=rated_at))
        if result.rowcount != 1:
            raise ToolInputError("This Report AI job was not registered for the current clinic connection.")
        await session.commit()
    record_report_ai_rating(score=score)
    return {"ok": True, "job_id": job_id, "score": score,
            "rated_at": rated_at.isoformat()}


async def purge_expired_jobs(*, now: datetime | None = None) -> int:
    """Delete prompts by immutable creation time, including idle accounts."""
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(ReportAiJobRating).where(ReportAiJobRating.created_at < cutoff))
        await session.commit()
    return int(result.rowcount or 0)

"""DB-backed agent feedback and verified known-issue helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
from typing import Any

from fastmcp.exceptions import ToolError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from observability_logging import RUNTIME_LOGGER
from storage import get_session_factory
from storage_models import (
    AgentFeedbackReport,
    FEEDBACK_CATEGORIES,
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_SEVERITIES,
    FEEDBACK_SEVERITY_LOW,
    FEEDBACK_SOURCE_AUTO,
    FEEDBACK_SOURCE_MODEL,
    FEEDBACK_STATUS_NEW,
    KNOWN_ISSUE_STATUS_ACKNOWLEDGED,
    KNOWN_ISSUE_STATUS_OPEN,
    KNOWN_ISSUE_STATUS_WORKAROUND_AVAILABLE,
    KnownIssue,
)
from tool_access_registry import TOOL_REQUIRED_SCOPES

REPORT_HINT = (
    'If this error is unclear or you suspect a Vetmanager MCP bug, call '
    'report_problem with related_tool="{tool_name}".'
)
REDACTION_VERSION = 2
MAX_AUTO_EVENTS_PER_MINUTE = 60
AUTO_EVENT_DEDUP_WINDOW = timedelta(minutes=15)
REPORT_ACCOUNT_LIMIT_PER_HOUR = 60
REPORT_TOKEN_LIMIT_PER_HOUR = 30
REPORT_RATE_WINDOW = timedelta(hours=1)
KNOWN_ISSUE_LOOKUP_TIMEOUT_SECONDS = 0.2
AUTO_EVENT_WRITE_TIMEOUT_SECONDS = 0.5
KB_AGENT_STATUS = KNOWN_ISSUE_STATUS_WORKAROUND_AVAILABLE
AUTO_EVENT_STATUSES = (
    KNOWN_ISSUE_STATUS_OPEN,
    KNOWN_ISSUE_STATUS_ACKNOWLEDGED,
    KNOWN_ISSUE_STATUS_WORKAROUND_AVAILABLE,
)
PRIVACY_REDACTIONS = frozenset({
    "email",
    "phone",
    "contextual_name",
    "contextual_patient",
    "contextual_address",
    "placeholder_seen",
    "sanitizer_error",
})

_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
    re.compile(r"(X-REST-API-KEY|authorization|cookie)\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"(api[_-]?key|password|token|secret)\s*[:=]\s*\S+", re.IGNORECASE),
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
_PLACEHOLDER_RE = re.compile(r"<(?:client|owner|patient|phone|address)>", re.IGNORECASE)
_NAME_VALUE = (
    r"(?:[A-ZА-ЯЁ][a-zа-яё]{2,})(?:\s+[A-ZА-ЯЁ][a-zа-яё]{2,}){0,2}"
    r"(?:\s+[A-ZА-ЯЁ]\.[A-ZА-ЯЁ]\.)?|[A-ZА-ЯЁ]\.[A-ZА-ЯЁ]\."
)
_CONTEXT_NAME_RE = re.compile(
    rf"\b(?P<label>(?i:client|owner|клиент|владелец))\s*(?P<sep>[:=])?\s+"
    rf"(?P<value>{_NAME_VALUE})\b"
)
_CONTEXT_PATIENT_RE = re.compile(
    r"\b(?P<label>(?i:pet|patient|питомец|пациент|кличка))\s*(?P<sep>[:=])?\s+"
    r"(?P<value>[A-ZА-ЯЁ][a-zа-яё]{2,})\b"
)
_CONTEXT_ADDRESS_RE = re.compile(
    r"\b(?P<label>address|адрес)\s*(?P<sep>[:=])\s*(?P<value>[^.;\n]{1,120})",
    re.IGNORECASE,
)
_VOLATILE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?\b|\b\d{6,}\b")
_SAFE_PARAM_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MATCH_FIELDS = {
    "related_tool",
    "error_fingerprint_hash",
    "http_status",
    "error_code",
    "normalized_error_text",
    "params_shape",
}
_MATCH_OPS = {"eq", "in", "contains_any", "contains_all", "has_keys", "missing_keys"}
_auto_event_stamps: deque[datetime] = deque()


@dataclass(slots=True)
class FeedbackIncident:
    related_tool: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_excerpt: str | None = None
    params_shape: list[str] | None = None


@dataclass(frozen=True, slots=True)
class SanitizeResult:
    text: str | None
    redactions: frozenset[str]


@dataclass(slots=True)
class KnownIssueMatch:
    id: int
    status: str
    title: str
    playbook: dict[str, Any]

    def as_response(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "title": self.title,
            "playbook": self.playbook,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(value: str, limit: int) -> str:
    return value[:limit]


def _is_phone_like(value: str) -> bool:
    compact = value.strip()
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return False
    if compact.startswith("+"):
        return True
    if not re.search(r"[\s().-]", compact):
        return False
    if digits.startswith(("7", "8")):
        return bool(re.match(
            r"^(?:7|8)[\s().-]*\(?\d{3}\)?[\s.-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}$",
            compact,
        ))
    return bool(re.match(r"^\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}$", compact))


def _redact_context(pattern: re.Pattern[str], text: str, category: str, redactions: set[str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        redactions.add(category)
        sep = match.groupdict().get("sep") or ""
        separator = sep if sep else " "
        if separator in {":", "="}:
            separator = f"{separator} "
        return f"{match.group('label')}{separator}[REDACTED]"

    return pattern.sub(_replace, text)


def sanitize_text_with_metadata(value: str | None, *, limit: int, required: bool = False) -> SanitizeResult:
    try:
        text = (value or "").strip()
        if required and not text:
            raise ToolError("Feedback field is required.")
        redactions: set[str] = set()
        if _PLACEHOLDER_RE.search(text):
            redactions.add("placeholder_seen")
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        if "[REDACTED]" in text:
            redactions.add("secret")
        if _EMAIL_RE.search(text):
            redactions.add("email")
            text = _EMAIL_RE.sub("[REDACTED]", text)

        def _phone_replace(match: re.Match[str]) -> str:
            candidate = match.group(0)
            if not _is_phone_like(candidate):
                return candidate
            redactions.add("phone")
            return "[REDACTED]"

        text = _PHONE_CANDIDATE_RE.sub(_phone_replace, text)
        text = _redact_context(_CONTEXT_ADDRESS_RE, text, "contextual_address", redactions)
        text = _redact_context(_CONTEXT_NAME_RE, text, "contextual_name", redactions)
        text = _redact_context(_CONTEXT_PATIENT_RE, text, "contextual_patient", redactions)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if required and not text:
            raise ToolError("Feedback field is empty after sanitization.")
        if not text:
            return SanitizeResult(None, frozenset(redactions))
        return SanitizeResult(_truncate(text, limit), frozenset(redactions))
    except ToolError:
        raise
    except Exception:
        return SanitizeResult("[REDACTED]", frozenset({"sanitizer_error"}))


def sanitize_text(value: str | None, *, limit: int, required: bool = False) -> str | None:
    return sanitize_text_with_metadata(value, limit=limit, required=required).text


def sanitize_params_shape(params_shape: list[str] | None) -> list[str] | None:
    if params_shape is None:
        return None
    if not isinstance(params_shape, list):
        raise ToolError("params_shape must be a list of safe parameter names.")
    cleaned: list[str] = []
    for item in params_shape:
        if not isinstance(item, str) or not _SAFE_PARAM_RE.match(item):
            raise ToolError("params_shape contains an unsafe parameter name.")
        if item not in cleaned:
            cleaned.append(item)
    return sorted(cleaned)[:32]


def normalize_error_text(value: str | None) -> str:
    text = sanitize_text(value, limit=1000) or ""
    text = text.lower()
    text = _VOLATILE_RE.sub("{volatile}", text)
    return re.sub(r"\s+", " ", text).strip()


def _fingerprint_pepper() -> str:
    pepper = os.environ.get("FEEDBACK_FINGERPRINT_PEPPER", "").strip()
    if not pepper:
        raise RuntimeError("FEEDBACK_FINGERPRINT_PEPPER is required for feedback fingerprints.")
    return pepper


def _fingerprint_pepper_or_none() -> str | None:
    pepper = os.environ.get("FEEDBACK_FINGERPRINT_PEPPER", "").strip()
    return pepper or None


def validate_feedback_runtime_config(*, database_url: str) -> None:
    """Fail production startup when feedback fingerprints cannot be generated."""
    if database_url.startswith("postgresql") and not os.environ.get("FEEDBACK_FINGERPRINT_PEPPER", "").strip():
        raise RuntimeError("FEEDBACK_FINGERPRINT_PEPPER is required for production feedback matching.")


def should_skip_report_hint(exc: BaseException) -> bool:
    message = str(exc).strip().lower()
    return message.startswith((
        "invalid ",
        "missing ",
        "params_shape ",
        "feedback field ",
    ))


def build_error_fingerprint_hash(incident: FeedbackIncident) -> str | None:
    normalized_text = normalize_error_text(incident.error_excerpt)
    if not any([
        incident.http_status,
        incident.error_code,
        normalized_text,
        incident.params_shape,
    ]):
        return None
    payload = {
        "tool": incident.related_tool or "",
        "http_status": incident.http_status,
        "error_code": (incident.error_code or "").strip().lower(),
        "error_text": normalized_text,
        "params_shape": sorted(incident.params_shape or []),
    }
    pepper = _fingerprint_pepper_or_none()
    if pepper is None:
        return None
    digest = hmac.new(
        pepper.encode("utf-8"),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"hmac-sha256:{digest}"


def _validate_string_list(value: Any, *, max_items: int, max_chars: int) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) > max_items:
        return None
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or len(item) > max_chars:
            return None
        result.append(item)
    return result


def validate_agent_playbook(raw_json: str | None) -> dict[str, Any] | None:
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    summary = data.get("summary")
    if not isinstance(summary, str) or len(summary) > 500:
        return None
    playbook: dict[str, Any] = {"version": 1, "summary": summary}
    for key in ("steps", "do_not_do", "recommended_tool_sequence"):
        max_chars = 128 if key == "recommended_tool_sequence" else 500
        value = _validate_string_list(data.get(key, []), max_items=8, max_chars=max_chars)
        if value is None:
            return None
        if key == "recommended_tool_sequence" and any(tool not in TOOL_REQUIRED_SCOPES for tool in value):
            return None
        playbook[key] = value
    user_template = data.get("user_message_template")
    if user_template is not None:
        if not isinstance(user_template, str) or len(user_template) > 800:
            return None
        playbook["user_message_template"] = user_template
    safe_to_retry = data.get("safe_to_retry", False)
    if not isinstance(safe_to_retry, bool):
        return None
    playbook["safe_to_retry"] = safe_to_retry
    return playbook


def validate_match_rules_json(raw_json: str | None) -> dict[str, Any] | None:
    if not raw_json:
        return None
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("version") != 1:
        return None
    conditions = data.get("all")
    if not isinstance(conditions, list) or len(conditions) > 16:
        return None
    for condition in conditions:
        if not isinstance(condition, dict):
            return None
        field = condition.get("field")
        op = condition.get("op")
        expected = condition.get("value")
        if field not in _MATCH_FIELDS or op not in _MATCH_OPS:
            return None
        if op in {"in", "contains_any", "contains_all", "has_keys", "missing_keys"}:
            if not isinstance(expected, list) or len(expected) > 32:
                return None
            if any(not isinstance(item, str) or len(item) > 500 for item in expected):
                return None
        elif isinstance(expected, str) and len(expected) > 500:
            return None
    return data


def _incident_value(incident: FeedbackIncident, field: str) -> Any:
    if field == "related_tool":
        return incident.related_tool
    if field == "error_fingerprint_hash":
        return build_error_fingerprint_hash(incident)
    if field == "http_status":
        return incident.http_status
    if field == "error_code":
        return incident.error_code
    if field == "normalized_error_text":
        return normalize_error_text(incident.error_excerpt)
    if field == "params_shape":
        return set(incident.params_shape or [])
    return None


def match_rules(raw_json: str | None, incident: FeedbackIncident) -> bool:
    data = validate_match_rules_json(raw_json)
    if data is None:
        return False
    conditions = data.get("all")
    for condition in conditions:
        field = condition.get("field")
        op = condition.get("op")
        expected = condition.get("value")
        actual = _incident_value(incident, field)
        if op == "eq":
            if actual != expected:
                return False
        elif op == "in":
            if not isinstance(expected, list) or actual not in expected:
                return False
        elif op == "contains_any":
            if not isinstance(expected, list) or not any(str(item) in str(actual or "") for item in expected):
                return False
        elif op == "contains_all":
            if not isinstance(expected, list) or not all(str(item) in str(actual or "") for item in expected):
                return False
        elif op == "has_keys":
            if not isinstance(expected, list) or not set(expected).issubset(actual or set()):
                return False
        elif op == "missing_keys":
            if not isinstance(expected, list) or set(expected).intersection(actual or set()):
                return False
        else:
            return False
    return True


async def _ordered_known_issue_candidates(
    session: AsyncSession,
    incident: FeedbackIncident,
    statuses: tuple[str, ...],
) -> AsyncIterator[KnownIssue]:
    fingerprint_hash = build_error_fingerprint_hash(incident)
    candidates = (
        await session.execute(
            select(KnownIssue)
            .where(KnownIssue.status.in_(statuses))
            .where((KnownIssue.related_tool == incident.related_tool) | (KnownIssue.related_tool.is_(None)))
            .order_by(KnownIssue.priority.asc(), KnownIssue.updated_at.desc(), KnownIssue.id.asc())
        )
    ).scalars().all()

    exact_matches: list[KnownIssue] = []
    rule_matches: list[KnownIssue] = []
    for issue in candidates:
        if fingerprint_hash and issue.error_fingerprint_hash == fingerprint_hash:
            exact_matches.append(issue)
            continue
        if match_rules(issue.match_rules_json, incident):
            rule_matches.append(issue)

    for issue in [*exact_matches, *rule_matches]:
        yield issue


async def find_known_issue_match(
    session: AsyncSession,
    incident: FeedbackIncident,
) -> KnownIssueMatch | None:
    async for issue in _ordered_known_issue_candidates(session, incident, (KB_AGENT_STATUS,)):
        playbook = validate_agent_playbook(issue.agent_playbook_json)
        if playbook is None:
            continue
        return KnownIssueMatch(
            id=issue.id,
            status=issue.status,
            title=issue.title,
            playbook=playbook,
        )
    return None


async def find_known_issue_for_auto_event(
    session: AsyncSession,
    incident: FeedbackIncident,
) -> KnownIssue | None:
    async for issue in _ordered_known_issue_candidates(session, incident, AUTO_EVENT_STATUSES):
        return issue
    return None


async def _enforce_report_rate_limit(
    session: AsyncSession,
    *,
    account_id: int | None,
    bearer_token_id: int | None,
) -> None:
    cutoff = _now() - REPORT_RATE_WINDOW
    if bearer_token_id is not None:
        token_count = await session.scalar(
            select(func.count())
            .select_from(AgentFeedbackReport)
            .where(AgentFeedbackReport.bearer_token_id == bearer_token_id)
            .where(AgentFeedbackReport.created_at >= cutoff)
        )
        if int(token_count or 0) >= REPORT_TOKEN_LIMIT_PER_HOUR:
            raise ToolError("Feedback rate limit exceeded for this token.")
    if account_id is not None:
        account_count = await session.scalar(
            select(func.count())
            .select_from(AgentFeedbackReport)
            .where(AgentFeedbackReport.account_id == account_id)
            .where(AgentFeedbackReport.created_at >= cutoff)
        )
        if int(account_count or 0) >= REPORT_ACCOUNT_LIMIT_PER_HOUR:
            raise ToolError("Feedback rate limit exceeded for this account.")


async def create_feedback_report(
    *,
    credentials,
    category: str,
    severity: str,
    summary: str,
    details: str,
    related_tool: str | None = None,
    related_call_id: str | None = None,
    request_id: str | None = None,
    http_status: int | None = None,
    error_code: str | None = None,
    error_excerpt: str | None = None,
    params_shape: list[str] | None = None,
    suggested_fix: str | None = None,
    reproduce: str | None = None,
) -> dict[str, Any]:
    if category not in FEEDBACK_CATEGORIES:
        raise ToolError("Invalid feedback category.")
    if severity not in FEEDBACK_SEVERITIES:
        raise ToolError("Invalid feedback severity.")
    safe_params_shape = sanitize_params_shape(params_shape)
    privacy_redactions: set[str] = set()

    def _free_text(value: str | None, *, limit: int, required: bool = False) -> str | None:
        result = sanitize_text_with_metadata(value, limit=limit, required=required)
        privacy_redactions.update(result.redactions)
        return result.text

    safe_error_excerpt = _free_text(error_excerpt, limit=1000)
    incident = FeedbackIncident(
        related_tool=sanitize_text(related_tool, limit=128),
        http_status=http_status,
        error_code=sanitize_text(error_code, limit=128),
        error_excerpt=safe_error_excerpt,
        params_shape=safe_params_shape,
    )
    fingerprint_hash = build_error_fingerprint_hash(incident)
    async with get_session_factory()() as session:
        await _enforce_report_rate_limit(
            session,
            account_id=getattr(credentials, "account_id", None),
            bearer_token_id=getattr(credentials, "bearer_token_id", None),
        )
        known_issue = await find_known_issue_match(session, incident)
        now = _now()
        known_issue_row = None
        if known_issue is not None:
            known_issue_row = await session.get(KnownIssue, known_issue.id)
            if known_issue_row is not None:
                known_issue_row.report_count += 1
                known_issue_row.first_seen_at = known_issue_row.first_seen_at or now
                known_issue_row.last_seen_at = now
        report = AgentFeedbackReport(
            source=FEEDBACK_SOURCE_MODEL,
            category=category,
            severity=severity,
            status=FEEDBACK_STATUS_NEW,
            account_id=getattr(credentials, "account_id", None),
            bearer_token_id=getattr(credentials, "bearer_token_id", None),
            related_tool=incident.related_tool,
            related_call_id=sanitize_text(related_call_id, limit=128),
            request_id=sanitize_text(request_id, limit=128),
            http_status=http_status,
            error_code=incident.error_code,
            params_shape_json=json.dumps(safe_params_shape, ensure_ascii=True) if safe_params_shape else None,
            summary=_free_text(summary, limit=240, required=True) or "",
            details=_free_text(details, limit=8000, required=True) or "",
            suggested_fix=_free_text(suggested_fix, limit=4000),
            reproduce=_free_text(reproduce, limit=4000),
            error_fingerprint_hash=fingerprint_hash,
            known_issue_id=known_issue.id if known_issue else None,
            redaction_version=REDACTION_VERSION,
            possible_pii=bool(PRIVACY_REDACTIONS.intersection(privacy_redactions)),
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)
    return {
        "ok": True,
        "feedback_id": report.id,
        "known_issue": known_issue.as_response() if known_issue else None,
        "message": "feedback_saved",
    }


def build_incident_from_exception(tool_name: str, exc: BaseException) -> FeedbackIncident:
    return FeedbackIncident(
        related_tool=tool_name,
        error_code=exc.__class__.__name__,
        error_excerpt=str(exc),
        params_shape=None,
    )


async def lookup_known_issue_for_error(tool_name: str, exc: BaseException) -> KnownIssueMatch | None:
    incident = build_incident_from_exception(tool_name, exc)
    async with get_session_factory()() as session:
        return await find_known_issue_match(session, incident)


def _auto_event_global_allowed(now: datetime) -> bool:
    cutoff = now - timedelta(minutes=1)
    while _auto_event_stamps and _auto_event_stamps[0] < cutoff:
        _auto_event_stamps.popleft()
    if len(_auto_event_stamps) >= MAX_AUTO_EVENTS_PER_MINUTE:
        return False
    _auto_event_stamps.append(now)
    return True


async def write_auto_feedback_event(*, credentials, tool_name: str, exc: BaseException) -> None:
    now = _now()
    incident = build_incident_from_exception(tool_name, exc)
    fingerprint_hash = build_error_fingerprint_hash(incident)
    if not fingerprint_hash:
        return
    account_id = getattr(credentials, "account_id", None)
    bearer_token_id = getattr(credentials, "bearer_token_id", None)
    if account_id is None and bearer_token_id is None:
        return
    async with get_session_factory()() as session:
        known_issue = await find_known_issue_for_auto_event(session, incident)
        if known_issue is None:
            return
        cutoff = now - AUTO_EVENT_DEDUP_WINDOW
        query = (
            select(func.count())
            .select_from(AgentFeedbackReport)
            .where(AgentFeedbackReport.source == FEEDBACK_SOURCE_AUTO)
            .where(AgentFeedbackReport.error_fingerprint_hash == fingerprint_hash)
            .where(AgentFeedbackReport.created_at >= cutoff)
        )
        if bearer_token_id is not None:
            query = query.where(AgentFeedbackReport.bearer_token_id == bearer_token_id)
        else:
            query = query.where(AgentFeedbackReport.account_id == account_id)
        existing = int((await session.scalar(query)) or 0)
        if existing:
            return
        if not _auto_event_global_allowed(now):
            RUNTIME_LOGGER.warning(
                "Dropped feedback auto-event by global cap",
                extra={"event_name": "feedback_auto_cap"},
            )
            return
        known_issue.report_count += 1
        known_issue.first_seen_at = known_issue.first_seen_at or now
        known_issue.last_seen_at = now
        session.add(AgentFeedbackReport(
            source=FEEDBACK_SOURCE_AUTO,
            category=FEEDBACK_CATEGORY_BUG,
            severity=FEEDBACK_SEVERITY_LOW,
            status=FEEDBACK_STATUS_NEW,
            account_id=account_id,
            bearer_token_id=bearer_token_id,
            related_tool=tool_name,
            summary=f"Matched known issue during {tool_name} failure",
            details="Auto-event created for a tool failure matching a verified known issue.",
            error_code=exc.__class__.__name__,
            error_fingerprint_hash=fingerprint_hash,
            known_issue_id=known_issue.id,
            redaction_version=REDACTION_VERSION,
            possible_pii=False,
        ))
        await session.commit()


async def augment_tool_error(tool_name: str, credentials, exc: ToolError) -> ToolError:
    hint = REPORT_HINT.format(tool_name=tool_name)
    known_issue: KnownIssueMatch | None = None
    try:
        known_issue = await asyncio.wait_for(
            lookup_known_issue_for_error(tool_name, exc),
            timeout=KNOWN_ISSUE_LOOKUP_TIMEOUT_SECONDS,
        )
    except Exception:
        RUNTIME_LOGGER.warning(
            "Known issue lookup failed",
            extra={"event_name": "known_issue_lookup_failed", "tool_name": tool_name},
            exc_info=True,
        )
    try:
        await asyncio.wait_for(
            write_auto_feedback_event(credentials=credentials, tool_name=tool_name, exc=exc),
            timeout=AUTO_EVENT_WRITE_TIMEOUT_SECONDS,
        )
    except Exception:
        RUNTIME_LOGGER.warning(
            "Feedback auto-event write failed",
            extra={"event_name": "feedback_auto_event_failed", "tool_name": tool_name},
            exc_info=True,
        )

    message = f"{exc}\n\n{hint}"
    if known_issue is not None:
        message += "\n\nKnown issue playbook: " + json.dumps(
            known_issue.as_response(),
            ensure_ascii=True,
            sort_keys=True,
        )
    return ToolError(message)

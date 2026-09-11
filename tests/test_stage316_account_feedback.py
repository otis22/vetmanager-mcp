"""Stage 316: authenticated human feedback from the account dashboard."""

from __future__ import annotations

from pathlib import Path

from fastmcp.exceptions import ToolError
import httpx
import pytest
from sqlalchemy import func, select

import error_tracking
import storage
from agent_feedback_service import create_account_human_feedback_report
from server import mcp
from storage import Base, create_database_engine
from storage_models import AgentFeedbackReport
import scripts.triage_agent_feedback as triage_cli
from web_auth import SESSION_COOKIE_NAME
from web_html import render_account_page
from web_security import reset_web_security_state


async def _prepare_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "feedback-web.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage316-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    storage.reset_storage_state()
    reset_web_security_state()
    engine = create_database_engine(f"sqlite:///{path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


async def _register(client: httpx.AsyncClient) -> None:
    page = await client.get("/register")
    token = page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    response = await client.post(
        "/register", data={"email": "stage316@example.com", "password": "Stage316-Pass-123", "csrf_token": token},
    )
    assert response.status_code == 303
    assert SESSION_COOKIE_NAME in client.cookies


async def _post_feedback(client: httpx.AsyncClient, **overrides: str) -> httpx.Response:
    page = await client.get("/account")
    token = page.text.split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
    data = {"asked": "Question", "received": "Answer", "expected": "Expected answer", "csrf_token": token}
    data.update(overrides)
    return await client.post("/account/agent-feedback", data=data)


@pytest.mark.asyncio
async def test_account_feedback_form_uses_csrf_and_stores_human_report(tmp_path, monkeypatch):
    await _prepare_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        await _register(client)
        page = await client.get("/account")
        assert page.status_code == 200
        assert 'data-testid="agent-feedback-form"' in page.text
        response = await _post_feedback(client)
    assert response.status_code == 200
    assert "Жалоба отправлена" in response.text
    async with storage.get_session_factory()() as session:
        report = (await session.execute(select(AgentFeedbackReport))).scalar_one()
    assert report.source == "human"
    assert report.account_id == 1
    assert "Question" in report.details
    assert report.redaction_version == 0
    assert report.is_human_web_submission is True
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_account_feedback_rejects_bad_csrf_without_storing(tmp_path, monkeypatch):
    await _prepare_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        await _register(client)
        response = await client.post("/account/agent-feedback", data={"asked": "a", "received": "b", "expected": "c"})
    assert response.status_code == 403
    async with storage.get_session_factory()() as session:
        count = await session.scalar(select(func.count()).select_from(AgentFeedbackReport))
    assert count == 0
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_human_account_bucket_is_not_spent_by_model_reports(tmp_path, monkeypatch):
    await _prepare_db(tmp_path, monkeypatch)
    monkeypatch.setattr("agent_feedback_service.REPORT_ACCOUNT_LIMIT_PER_HOUR", 1)
    async with storage.get_session_factory()() as session:
        session.add(AgentFeedbackReport(source="model", category="bug", severity="low", status="new", account_id=1, summary="model", details="model"))
        session.add(AgentFeedbackReport(source="human", category="bug", severity="low", status="new", account_id=1, bearer_token_id=99, summary="mcp human", details="mcp human"))
        await session.commit()
    result = await create_account_human_feedback_report(account_id=1, asked="a", received="b", expected="c")
    assert result["ok"] is True
    with pytest.raises(ToolError, match="rate limit"):
        await create_account_human_feedback_report(account_id=1, asked="a", received="b", expected="c")
    storage.reset_storage_state()


def test_feedback_sentry_event_drops_post_body_and_stack_values():
    private = "private form text"
    event = {
        "request": {"url": "https://service.example/account/agent-feedback", "data": {"asked": private}},
        "exception": {"values": [{"value": private, "stacktrace": {"frames": [{"vars": {"form": private}}]}}]},
    }
    sanitized = error_tracking._sanitize_event(event, None)
    assert sanitized is not None
    assert "data" not in sanitized["request"]
    assert private not in repr(sanitized)


def test_triage_masks_raw_account_feedback_body():
    report = AgentFeedbackReport(
        id=1, source="human", category="other", severity="medium", status="new",
        summary="Account dashboard feedback", details="Contact person@example.com, phone +7 999 123-45-67",
        redaction_version=0, possible_pii=True, is_human_web_submission=True,
    )
    body = "\n".join(triage_cli._report_body_lines(report))
    assert "person@example.com" not in body
    assert "+7 999" not in body


def test_feedback_contact_is_optional_and_runtime_only(monkeypatch):
    account = type("Account", (), {"id": 1, "email": "stage316@example.com", "status": "active"})()
    kwargs = dict(csrf_token="csrf", script_nonce="nonce", active_connection_count=0, bearer_token_count=0,
                  active_connection=None, integration_health_status="unknown", integration_health_reason="none",
                  bearer_tokens=[], oauth_grants=[])
    monkeypatch.delenv("FEEDBACK_CONTACT_EMAIL", raising=False)
    assert "Вопросы и жалобы напрямую" not in render_account_page(account, **kwargs)
    configured = "owner" + "@" + "example" + ".com"
    monkeypatch.setenv("FEEDBACK_CONTACT_EMAIL", configured)
    html = render_account_page(account, **kwargs)
    assert "Вопросы и жалобы напрямую" in html
    assert configured in html


def _personal_email_domain_leaks(files: list[Path]) -> list[Path]:
    suffix = "." + "com"
    forbidden = tuple("@" + provider + suffix for provider in ("gmail", "yandex", "mail", "bk", "inbox", "list"))
    return [path for path in files if any(token in path.read_text(encoding="utf-8", errors="ignore").lower() for token in forbidden)]


def test_repository_has_no_personal_email_domain_literals():
    root = Path(__file__).resolve().parents[1]
    # The test image deliberately has no git binary. Scanning the checked-out
    # repository tree (excluding runtime caches and local env) covers every
    # tracked source/documentation file that can be published.
    files = [
        path for path in root.rglob("*")
        if path.is_file() and not any(part in {".git", ".venv", ".pytest_cache", "__pycache__"} for part in path.parts)
        and path.name != ".env" and path.suffix != ".pyc"
    ]
    assert _personal_email_domain_leaks(files) == []


def test_personal_email_domain_guard_detects_a_leak(tmp_path):
    leaked = tmp_path / "leak.txt"
    leaked.write_text("x" + "@" + "gmail" + ".com", encoding="utf-8")
    assert _personal_email_domain_leaks([leaked]) == [leaked]

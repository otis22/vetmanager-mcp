"""Stage 379: prepared prompt/notice observations and bounded guidance signals."""

import os
import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent

from server import mcp, _prompt_metrics
from service_metrics import (
    record_prompt_request, record_token_expiry_notice_issued,
    render_prometheus_metrics, reset_service_metrics, snapshot_service_metrics,
)
from storage_models import Account, ServiceBearerToken
from tool_error_tracking import ToolErrorTrackingMiddleware
import token_expiry_notice


MUTATION = os.environ.get("STAGE379_MUTATION", "")


@pytest.mark.asyncio
async def test_prompt_hooks_count_only_success_and_registered_names(monkeypatch):
    reset_service_metrics()
    async with Client(mcp) as client:
        catalogue = await client.list_prompts()
        await client.get_prompt("welcome_first_session", arguments={})
        await client.get_prompt("find_client", arguments={"query": "private-sentinel-79991234567"})
        with pytest.raises(Exception):
            await client.get_prompt("private-unknown-79991234567", arguments={"query": "private-sentinel"})
    names = {prompt.name for prompt in catalogue}
    assert names == _prompt_metrics.allowed_names
    data = snapshot_service_metrics()["prompt_requests_total"]
    assert {k for k in data if k.startswith("list|")} == {f"list|{name}" for name in names}
    assert all(count == 1 for key, count in data.items() if key.startswith("list|"))
    assert data["get|welcome_first_session"] == 1
    assert data["get|find_client"] == 1
    assert "get|private-unknown-79991234567" not in data
    record_prompt_request(method="get", prompt="private-unknown-79991234567", allowed_names=_prompt_metrics.allowed_names)
    rendered = render_prometheus_metrics()
    assert 'vetmanager_prompt_requests_total{method="get",prompt="other"} 1' in rendered
    assert "private-sentinel" not in rendered and "private-unknown" not in rendered
    assert "79991234567" not in rendered
    for line in rendered.splitlines():
        if line.startswith("vetmanager_prompt_requests_total{"):
            assert re.fullmatch(r'vetmanager_prompt_requests_total\{method="(?:list|get)",prompt="(?:[a-z_]+|other)"\} \d+', line)
    if MUTATION == "duplicate_list":
        record_prompt_request(method="list", prompt="welcome_first_session", allowed_names=_prompt_metrics.allowed_names)
    assert snapshot_service_metrics()["prompt_requests_total"]["list|welcome_first_session"] == 1


@pytest.mark.asyncio
async def test_prompt_hook_failure_and_deduplication():
    reset_service_metrics()
    async def listed(_):
        return [SimpleNamespace(name="welcome_first_session"), SimpleNamespace(name="welcome_first_session")]
    await _prompt_metrics.on_list_prompts(None, listed)
    assert snapshot_service_metrics()["prompt_requests_total"] == {"list|welcome_first_session": 1}
    async def failed(_):
        raise ValueError("private-sentinel")
    with pytest.raises(ValueError):
        await _prompt_metrics.on_list_prompts(None, failed)
    with pytest.raises(ValueError):
        await _prompt_metrics.on_get_prompt(SimpleNamespace(message=SimpleNamespace(name="welcome_first_session")), failed)
    assert snapshot_service_metrics()["prompt_requests_total"] == {"list|welcome_first_session": 1}


@pytest.mark.asyncio
async def test_notice_outcomes_and_claim_buckets(tmp_path, sqlite_session_factory_builder, monkeypatch):
    reset_service_metrics()
    factory = await sqlite_session_factory_builder(tmp_path / "stage379.db")
    now = datetime.now(timezone.utc)
    async with factory() as session:
        account = Account(email="stage379@example.test", status="active")
        session.add(account)
        await session.flush()
        tokens = []
        for days in (1, 2, 7, 8, 14, 15):
            token = ServiceBearerToken(account_id=account.id, name=f"expiry-{days}")
            token.set_raw_token(f"vm_st_{days:02d}_stage379")
            token.expires_at = now + timedelta(days=days) - timedelta(seconds=1)
            session.add(token)
            tokens.append(token)
        await session.commit()
        account_id = account.id
        ids = [token.id for token in tokens]
    monkeypatch.setattr(token_expiry_notice, "get_session_factory", lambda: factory)
    middleware = ToolErrorTrackingMiddleware()
    context = SimpleNamespace(message=SimpleNamespace(name="get_clients"))
    async def call_for(token_id):
        async def success(_):
            if token_id is not None:
                token_expiry_notice.set_notice_subject(account_id, token_id)
            return ToolResult(content=[TextContent(type="text", text="[]")])
        return await middleware.on_call_tool(context, success)
    for token_id in ids[:5]:
        assert len((await call_for(token_id)).content) == 2
    assert len((await call_for(ids[0])).content) == 1
    assert len((await call_for(ids[5])).content) == 1
    assert len((await call_for(None)).content) == 1
    data = snapshot_service_metrics()
    assert data["token_expiry_notice_issued_total"] == {"1d": 1, "7d": 2, "14d": 2}
    assert data["token_expiry_notice_skipped_total"] == {"claim_recent": 1, "ineligible": 1, "no_subject": 1}
    async def timeout(*args, **kwargs):
        raise TimeoutError("deadline")
    monkeypatch.setattr(token_expiry_notice, "claim_expiry_notice", timeout)
    assert len((await call_for(ids[0])).content) == 1
    assert snapshot_service_metrics()["token_expiry_notice_skipped_total"]["deadline"] == 1
    async def unavailable(*args, **kwargs):
        raise RuntimeError("private-sentinel")
    monkeypatch.setattr(token_expiry_notice, "claim_expiry_notice", unavailable)
    assert len((await call_for(ids[0])).content) == 1
    assert snapshot_service_metrics()["token_expiry_notice_skipped_total"]["unavailable"] == 1
    rendered = render_prometheus_metrics()
    assert 'vetmanager_token_expiry_notice_issued_total{threshold="1d",outcome="appended"} 1' in rendered
    assert 'vetmanager_token_expiry_notice_skipped_total{outcome="deadline"} 1' in rendered
    assert "vm_st_" not in rendered
    for line in rendered.splitlines():
        if line.startswith("vetmanager_token_expiry_notice_issued_total{"):
            assert re.fullmatch(r'vetmanager_token_expiry_notice_issued_total\{threshold="(?:1d|7d|14d)",outcome="appended"\} \d+', line)
        if line.startswith("vetmanager_token_expiry_notice_skipped_total{"):
            assert re.fullmatch(r'vetmanager_token_expiry_notice_skipped_total\{outcome="(?:claim_recent|deadline|no_subject|ineligible|unavailable)"\} \d+', line)
    reset_service_metrics()
    assert snapshot_service_metrics()["token_expiry_notice_issued_total"] == {}
    assert snapshot_service_metrics()["token_expiry_notice_skipped_total"] == {}


def test_guidance_registry_help_and_reset():
    reset_service_metrics()
    record_token_expiry_notice_issued(1)
    text = render_prometheus_metrics()
    signals = (
        "known_issue_lookups_total", "report_ai_empty_preview_guidance_issued_total",
        "report_ai_empty_preview_guidance_jobs_total", "report_ai_empty_preview_guidance_outcomes_total",
        "first_session_eligible_accounts", "first_session_report_saved_7d_accounts",
        "first_session_tool_success_7d_accounts", "first_session_tool_time_median_seconds",
        "activation_funnel_accounts", "token_expiry_notice_issued_total",
        "token_expiry_notice_skipped_total", "prompt_requests_total",
        "report_ai_job_transitions_total", "report_ai_job_terminal_outcomes_total",
        "report_ai_save_attempts_total",
    )
    for name in signals:
        assert f"# HELP vetmanager_{name}" in text
        assert f"# TYPE vetmanager_{name}" in text
    table = Path("PRD/этап-379-наблюдаемость-промптов-и-notice.md").read_text().split("## Аудит agent-facing подсказок", 1)[1].split("## Архитектурное решение", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| ") and not line.startswith("| Подсказка")]
    assert len(rows) == 6
    assert all("`vetmanager_" in row and "|" in row for row in rows)
    for name in ("prompt_requests_total", "token_expiry_notice_issued_total", "token_expiry_notice_skipped_total"):
        assert f"# HELP vetmanager_{name}" in text
        assert f"# TYPE vetmanager_{name} counter" in text
    for line in text.splitlines():
        if line.startswith("# HELP vetmanager_prompt_requests_total") or line.startswith("# HELP vetmanager_token_expiry_notice_"):
            assert "delivery" in line or "prepared" in line or "responses" in line
            assert "delivered" not in line and "read by" not in line
    reset_service_metrics()
    assert not any(line.startswith("vetmanager_token_expiry_notice_issued_total{") for line in render_prometheus_metrics().splitlines())

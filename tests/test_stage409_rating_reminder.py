"""Stage 409: a ready report reminds the owning connection until it rates."""

import os

import httpx
import fakeredis
import pytest
import respx

import service_metrics
import storage
from report_ai_rating_service import has_unrated_job, rate_job, record_created_job
from server import mcp
from storage import Base, create_database_engine
from storage_models import Account
from shared_metric_counters import COUNTERS_KEY, REPORT_AI_RATING_REMINDERS_KEY, RedisMetricCounters
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS
from tools.report_ai import REPORT_AI_RATING_GUIDANCE
import tools.report_ai as report_ai


@pytest.fixture
async def rating_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rating409.db'}")
    storage.reset_storage_state()
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    async with storage.get_session_factory()() as session:
        session.add(Account(email="stage409@example.test"))
        await session.commit()
    service_metrics.reset_service_metrics()
    yield
    storage.reset_storage_state()


def _payload(result):
    return result.structured_content


@pytest.mark.asyncio
@respx.mock
async def test_reminder_lifecycle_on_both_read_tools(rating_db):
    billing_mock()
    status = {"success": True, "data": {"job": {"id": 409, "status": "saved"}}}
    rows = {"success": True, "data": {"columns": ["count"], "rows": [{"count": "2"}], "total": 1, "limited": False}}
    respx.get(f"{BASE}/rest/api/report-ai-job/409").mock(return_value=httpx.Response(200, json=status))
    respx.get(f"{BASE}/rest/api/report-ai-job/409/data").mock(return_value=httpx.Response(200, json=rows))
    await record_created_job(account_id=1, connection_id=1, domain="testclinic",
                             job_id=409, intent_text="Количество приёмов")
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        before_status = _payload(await mcp.call_tool("get_report_ai_job", {"job_id": 409}))
        before_rows = _payload(await mcp.call_tool("get_report_ai_job_data", {"job_id": 409}))
        assert "rate_report_ai_job(job_id, score, intent_text)" in before_status["data"]["job"]["mcp_rating_reminder"]
        assert "get_report_ai_job_data" in before_status["data"]["job"]["mcp_rating_reminder"]
        assert "rate_report_ai_job(job_id, score, intent_text)" in before_rows["data"]["mcp_rating_reminder"]
        assert "vetmanager_report_ai_rating_reminders_total 2" in service_metrics.render_prometheus_metrics()
        await rate_job(account_id=1, connection_id=1, domain="testclinic", job_id=409,
                       score=8, intent_text="Количество приёмов")
        after_status = _payload(await mcp.call_tool("get_report_ai_job", {"job_id": 409}))
        after_rows = _payload(await mcp.call_tool("get_report_ai_job_data", {"job_id": 409}))
    assert "mcp_rating_reminder" not in after_status["data"]["job"]
    assert "mcp_rating_reminder" not in after_rows["data"]
    assert "vetmanager_report_ai_rating_reminders_total 2" in service_metrics.render_prometheus_metrics()


@pytest.mark.asyncio
@respx.mock
async def test_reminder_requires_terminal_owned_unrated_job(rating_db):
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/409").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": {"id": 409, "status": "ready_to_save"}}}))
    await record_created_job(account_id=1, connection_id=1, domain="testclinic",
                             job_id=409, intent_text="Количество приёмов")
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        pending = _payload(await mcp.call_tool("get_report_ai_job", {"job_id": 409}))
    assert "mcp_rating_reminder" not in pending["data"]["job"]
    route.mock(return_value=httpx.Response(200, json={"success": True, "data": {"job": {"id": 409, "status": "built"}}}))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        built = _payload(await mcp.call_tool("get_report_ai_job", {"job_id": 409}))
    assert "mcp_rating_reminder" in built["data"]["job"]
    assert await has_unrated_job(account_id=1, connection_id=2, domain="testclinic", job_id=409) is False
    assert await has_unrated_job(account_id=1, connection_id=1, domain="otherclinic", job_id=409) is False


@pytest.mark.asyncio
@respx.mock
async def test_data_failure_and_lookup_timeout_leave_payload_intact(rating_db, monkeypatch):
    billing_mock()
    data_route = respx.get(f"{BASE}/rest/api/report-ai-job/409/data").mock(
        return_value=httpx.Response(200, json={"success": False, "data": {"rows": []}}))
    status_route = respx.get(f"{BASE}/rest/api/report-ai-job/409").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": {"id": 409, "status": "saved"}}}))
    await record_created_job(account_id=1, connection_id=1, domain="testclinic",
                             job_id=409, intent_text="Количество приёмов")
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        failed = _payload(await mcp.call_tool("get_report_ai_job_data", {"job_id": 409}))
    assert "mcp_rating_reminder" not in failed.get("data", {})
    data_route.mock(return_value=httpx.Response(200, json={"success": True, "data": {"rows": []}}))

    async def stalled_lookup(**_):
        import asyncio
        await asyncio.sleep(1)
        return True

    monkeypatch.setattr(report_ai, "has_unrated_job", stalled_lookup)
    monkeypatch.setattr(report_ai, "REPORT_AI_RATING_REMINDER_TIMEOUT_SECONDS", 0.01)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        status = _payload(await mcp.call_tool("get_report_ai_job", {"job_id": 409}))
        data = _payload(await mcp.call_tool("get_report_ai_job_data", {"job_id": 409}))
    assert status_route.call_count == 1
    assert status["data"]["job"]["status"] == "saved"
    assert data["data"]["rows"] == []
    assert "mcp_rating_reminder" not in status["data"]["job"]
    assert "mcp_rating_reminder" not in data["data"]
    assert "vetmanager_report_ai_rating_reminders_total 0" in service_metrics.render_prometheus_metrics()


def test_reminder_metric_uses_separate_key_for_old_workers():
    redis = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(redis)
    backend.increment("report_ai_rating_reminders_total", "")
    assert redis.hgetall(COUNTERS_KEY) == {}
    assert redis.get(REPORT_AI_RATING_REMINDERS_KEY) == "1"
    assert backend.snapshot()["report_ai_rating_reminders_total"] == 1


@pytest.mark.asyncio
async def test_canonical_rating_text():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    for name in ("create_report_ai_job", "get_report_ai_job", "get_report_ai_job_data", "rate_report_ai_job"):
        description = tools[name].description
        assert "rate_report_ai_job" in description
        assert "intent_text" in description
        assert "voluntary" not in description.lower()
        assert "добровольн" not in description.lower()
    assert "final step" in REPORT_AI_RATING_GUIDANCE.lower()
    assert "intent_text and score are required; comment is optional" in REPORT_AI_RATING_GUIDANCE
    assert "voluntary" not in REPORT_AI_RATING_GUIDANCE.lower()
    assert "voluntary" not in " ".join(SPECIAL_TOOL_DESCRIPTIONS.values()).lower()

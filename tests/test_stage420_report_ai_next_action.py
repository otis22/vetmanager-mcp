"""Stage 420: machine-readable continuation across the Report AI route."""

import httpx
import os
import pytest
import respx

import service_metrics
import storage
import tools.report_ai as report_ai
from server import mcp
from storage import Base, create_database_engine
from storage_models import Account
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from report_ai_rating_service import rate_job, record_created_job


@pytest.fixture
async def rating_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rating420.db'}")
    storage.reset_storage_state()
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    async with storage.get_session_factory()() as session:
        session.add(Account(email="stage420@example.test"))
        await session.commit()
    service_metrics.reset_service_metrics()
    yield
    storage.reset_storage_state()


def _job(status, **fields):
    return {"success": True, "data": {"job": {"id": 420, "status": status, **fields}}}


def _action(job):
    report_ai._annotate_report_ai_next_action(job)
    return job.get("next_action")


@pytest.mark.parametrize("status", ["queued", "recognizing", "building_preview"])
def test_active_status_has_bounded_poll(status):
    action = _action({"id": 420, "status": status})
    assert action["call"] == {"tool": "get_report_ai_job", "arguments": {"job_id": 420, "wait_seconds": 30}}
    assert action["required_args"] == ["job_id"]


@pytest.mark.parametrize("status", ["saved", "existing_report_matched"])
def test_ready_rows_status_has_data_call(status):
    action = _action({"id": 420, "status": status})
    assert action["call"] == {"tool": "get_report_ai_job_data", "arguments": {"job_id": 420}}
    assert action["required_args"] == ["job_id"]


def test_choice_save_and_terminal_keep_contract():
    choose = _action({"id": "420", "status": "needs_confirmation", "candidates": [{"report_id": 17}]})
    assert {call["tool"] for call in choose["calls"]} == {
        "confirm_report_ai_job_candidate", "reject_report_ai_job_candidate"}
    assert choose["required_args"] == ["job_id"]
    assert "approval" in choose["guidance"].lower()
    save = _action({"id": 420, "status": "ready_to_save"})
    assert save["call"]["tool"] == "save_report_ai_job_as_report"
    assert save["required_args"] == ["job_id", "title"]
    assert "consent" in save["guidance"].lower()
    failed = _action({"id": 420, "status": "failed"})
    assert failed["call"] == {"tool": "rate_report_ai_job", "arguments": {"job_id": 420, "score": 1}}
    assert failed["required_args"] == ["job_id", "score", "intent_text"]
    for status in ("rejected", "cancelled", "built"):
        action = _action({"id": 420, "status": status})
        assert action and "call" not in action
    for job in ({"id": None, "status": "saved"}, {"id": 420, "status": "future_status"}):
        assert _action(job) is None


def test_poll_diagnostics_override_active_call():
    stalled = _action({"id": 420, "status": "queued", "mcp_queue_diagnostics": {"stop_automatic_polling": True}})
    assert stalled["type"] == "poll_paused" and "call" not in stalled
    timeout = _action({"id": 420, "status": "queued", "mcp_wait_diagnostics": {"code": "wait_timeout"}})
    assert timeout["type"] == "poll_paused" and "call" not in timeout
    denied = _action({"id": 420, "status": "queued", "mcp_wait_diagnostics": {"code": "missing_analytics_scope"}})
    assert denied["type"] == "access_required" and "call" not in denied


@pytest.mark.asyncio
@respx.mock
async def test_create_and_status_public_payloads(monkeypatch):
    billing_mock()
    async def registered(**_kwargs):
        return True
    monkeypatch.setattr(report_ai, "record_created_job", registered)
    respx.post(f"{BASE}/rest/api/report-ai-job").mock(return_value=httpx.Response(201, json=_job("queued")))
    respx.get(f"{BASE}/rest/api/report-ai-job/420").mock(return_value=httpx.Response(200, json=_job("saved")))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        created = (await mcp.call_tool("create_report_ai_job", {"intent_text": "Счёт приёмов"})).structured_content
        status = (await mcp.call_tool("get_report_ai_job", {"job_id": 420})).structured_content
    assert created["data"]["job"]["next_action"]["call"]["tool"] == "get_report_ai_job"
    assert status["data"]["job"]["next_action"]["call"]["tool"] == "get_report_ai_job_data"
    assert created["data"]["job"]["mcp_rating_guidance"] == report_ai.REPORT_AI_RATING_GUIDANCE
    assert status["data"]["job"]["status"] == "saved"


@pytest.mark.asyncio
@respx.mock
async def test_data_rating_then_complete_preserves_rows_and_reminder(rating_db):
    billing_mock()
    rows = {"success": True, "data": {"columns": ["count"], "rows": [{"count": "2"}], "total": 1, "limited": False}}
    respx.get(f"{BASE}/rest/api/report-ai-job/420/data").mock(return_value=httpx.Response(200, json=rows))
    await record_created_job(account_id=1, connection_id=1, domain="testclinic", job_id=420,
                             intent_text="Счёт приёмов")
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        before = (await mcp.call_tool("get_report_ai_job_data", {"job_id": 420})).structured_content
        await rate_job(account_id=1, connection_id=1, domain="testclinic", job_id=420,
                       score=8, intent_text="Счёт приёмов")
        after = (await mcp.call_tool("get_report_ai_job_data", {"job_id": 420})).structured_content
    action = before["data"]["next_action"]
    assert action["call"] == {"tool": "rate_report_ai_job", "arguments": {"job_id": 420}}
    assert action["required_args"] == ["job_id", "score", "intent_text"]
    assert "get_client_by_id(client_id)" in action["guidance"]
    assert "clients.read" in action["guidance"]
    assert before["data"]["mcp_rating_reminder"] == report_ai.REPORT_AI_RATING_REMINDER
    assert before["data"]["rows"] == after["data"]["rows"]
    assert after["data"]["next_action"]["type"] == "complete"
    assert "call" not in after["data"]["next_action"]
    assert "mcp_rating_reminder" not in after["data"]


@pytest.mark.asyncio
@respx.mock
async def test_write_only_create_names_missing_read_access(monkeypatch):
    from token_scopes import SCOPE_REPORT_AI_WRITE
    billing_mock()
    async def registered(**_kwargs):
        return True
    monkeypatch.setattr(report_ai, "record_created_job", registered)
    respx.post(f"{BASE}/rest/api/report-ai-job").mock(return_value=httpx.Response(201, json=_job("queued")))
    headers, runtime = bearer_runtime_patch(scopes=(SCOPE_REPORT_AI_WRITE,))
    with headers, runtime:
        created = (await mcp.call_tool("create_report_ai_job", {"intent_text": "Счёт приёмов"})).structured_content
    action = created["data"]["job"]["next_action"]
    assert action["type"] == "access_required" and action["required_scope"] == "analytics.read"
    assert "call" not in action


@pytest.mark.asyncio
@respx.mock
async def test_successful_save_and_confirm_return_data_action():
    billing_mock()
    for suffix in ("save", "confirm"):
        respx.post(f"{BASE}/rest/api/report-ai-job/420/{suffix}").mock(
            return_value=httpx.Response(200, json={"success": True, "data": {"report_id": 91}}))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        saved = (await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 420, "title": "MCP Счёт приёмов за октябрь 2026"})).structured_content
        confirmed = (await mcp.call_tool("confirm_report_ai_job_candidate", {
            "job_id": 420, "report_id": 91})).structured_content
    for payload in (saved, confirmed):
        assert payload["data"]["report_id"] == 91
        assert payload["data"]["next_action"]["call"] == {
            "tool": "get_report_ai_job_data", "arguments": {"job_id": 420}}


@pytest.mark.asyncio
@respx.mock
async def test_truncated_and_read_only_data_prioritize_export(rating_db):
    from token_scopes import SCOPE_ANALYTICS_READ
    billing_mock()
    rows = {"success": True, "data": {"columns": ["count"], "rows": [{"count": "2"}],
                                      "total": 10001, "limited": True}}
    respx.get(f"{BASE}/rest/api/report-ai-job/420/data").mock(return_value=httpx.Response(200, json=rows))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        writable = (await mcp.call_tool("get_report_ai_job_data", {"job_id": 420})).structured_content
    assert writable["data"]["next_action"]["call"]["tool"] == "get_report_ai_job_export"
    headers, runtime = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers, runtime:
        readonly = (await mcp.call_tool("get_report_ai_job_data", {"job_id": 420})).structured_content
    assert readonly["data"]["next_action"]["type"] == "access_required"
    assert "call" not in readonly["data"]["next_action"]


@pytest.mark.asyncio
@respx.mock
async def test_unregistered_data_can_rate_but_read_only_cannot(rating_db):
    from token_scopes import SCOPE_ANALYTICS_READ
    billing_mock()
    rows = {"success": True, "data": {"columns": ["count"], "rows": [], "total": 0, "limited": False}}
    respx.get(f"{BASE}/rest/api/report-ai-job/420/data").mock(return_value=httpx.Response(200, json=rows))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        writable = (await mcp.call_tool("get_report_ai_job_data", {"job_id": 420})).structured_content
    assert writable["data"]["next_action"]["call"]["tool"] == "rate_report_ai_job"
    assert "mcp_rating_reminder" not in writable["data"]
    headers, runtime = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers, runtime:
        readonly = (await mcp.call_tool("get_report_ai_job_data", {"job_id": 420})).structured_content
    assert readonly["data"]["next_action"]["required_scope"] == "report_ai.write"


@pytest.mark.asyncio
async def test_bounded_wait_observed_age_stops_machine_poll(monkeypatch):
    monkeypatch.setattr(report_ai, "_observe_report_ai_queue", lambda *_args, **_kwargs: 901)
    payload = await report_ai._annotate_report_ai_wait_payload(_job("queued"))
    report_ai._finish_report_ai_job_action(payload)
    job = payload["data"]["job"]
    assert job["mcp_queue_diagnostics"]["stop_automatic_polling"] is True
    assert job["next_action"]["type"] == "poll_paused"
    assert "call" not in job["next_action"]


@pytest.mark.asyncio
@respx.mock
async def test_read_only_status_does_not_advertise_save():
    from token_scopes import SCOPE_ANALYTICS_READ
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/420").mock(
        return_value=httpx.Response(200, json=_job("ready_to_save")))
    headers, runtime = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers, runtime:
        status = (await mcp.call_tool("get_report_ai_job", {"job_id": 420})).structured_content
    action = status["data"]["job"]["next_action"]
    assert action["required_scope"] == "report_ai.write" and "call" not in action


def test_failed_payload_never_advertises_next_action():
    payload = {"success": False, "data": {"job": {"id": 420, "status": "saved"}}}
    annotated = report_ai._annotate_report_ai_workarounds(payload)
    assert "next_action" not in annotated["data"]["job"]

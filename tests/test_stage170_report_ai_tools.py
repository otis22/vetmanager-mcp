import json
import asyncio
import logging

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import service_metrics
from server import mcp
from scripts.seed_known_issues import SEED_ISSUES
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import (
    SCOPE_ANALYTICS_READ,
    SCOPE_ANALYTICS_WRITE,
    SCOPE_CLIENTS_READ,
    SCOPE_REPORT_AI_WRITE,
)
from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS
import tools.report_ai as report_ai
import vetmanager_client


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch(
    *,
    scopes=(SCOPE_ANALYTICS_READ, SCOPE_REPORT_AI_WRITE),
    is_depersonalized: bool = False,
):
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        scopes=scopes,
        is_depersonalized=is_depersonalized,
    )


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


def _structured(result) -> dict:
    return result.structured_content


@pytest.mark.asyncio
async def test_report_ai_prompt_helper_registered_and_mentions_data_boundary():
    prompt = await mcp.get_prompt("report_ai_prompt_helper")

    assert prompt is not None
    rendered = await prompt.render(arguments={})
    body = "\n".join(str(message.content) for message in rendered.messages)

    assert "ready_to_save" in body
    assert "saved" in body
    assert "existing_report_matched" in body
    assert "Do not write SQL" in body
    assert "good.id" in body
    assert "код/артикул/наименование товара" in body


@pytest.mark.asyncio
async def test_get_report_ai_prompt_helper_tool_matches_prompt_body():
    names = {tool.name for tool in await mcp.list_tools()}
    assert "get_report_ai_prompt_helper" in names

    prompt = await mcp.get_prompt("report_ai_prompt_helper")
    rendered = await prompt.render(arguments={})
    prompt_body = "\n".join(message.content.text for message in rendered.messages)

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_CLIENTS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_prompt_helper", {})

    helper_text = _structured(result)["helper_text"]
    assert helper_text == prompt_body
    assert "ready_to_save" in helper_text
    assert "saved" in helper_text
    assert "existing_report_matched" in helper_text
    assert "Do not write SQL" in helper_text
    assert "good.id" in helper_text
    assert "код/артикул/наименование товара" in helper_text


@pytest.mark.asyncio
async def test_get_report_ai_prompt_helper_scope_free_but_authenticated():
    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_CLIENTS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_prompt_helper", {})

    assert "helper_text" in _structured(result)

    empty_headers_patch, empty_runtime_patch = bearer_runtime_patch(scopes=())
    with empty_headers_patch, empty_runtime_patch:
        with pytest.raises(ToolError, match="not permitted"):
            await mcp.call_tool("get_report_ai_prompt_helper", {})


@pytest.mark.asyncio
async def test_get_report_ai_prompt_helper_depersonalized_token_preserves_text():
    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_CLIENTS_READ,))
    with headers_patch, runtime_patch:
        normal = await mcp.call_tool("get_report_ai_prompt_helper", {})

    dep_headers_patch, dep_runtime_patch = bearer_runtime_patch(
        scopes=(SCOPE_CLIENTS_READ,),
        is_depersonalized=True,
    )
    with dep_headers_patch, dep_runtime_patch:
        depersonalized = await mcp.call_tool("get_report_ai_prompt_helper", {})

    assert _structured(depersonalized)["helper_text"] == _structured(normal)["helper_text"]


def test_report_ai_guidance_descriptions_name_helper_and_fallback_policy():
    create_description = SPECIAL_TOOL_DESCRIPTIONS["create_report_ai_job"]
    assert "get_report_ai_prompt_helper" in create_description
    assert "report_ai_prompt_helper" in create_description

    data_description = SPECIAL_TOOL_DESCRIPTIONS["get_report_ai_job_data"]
    assert "limited=true" in data_description
    assert "narrow" in data_description.lower() or "refine" in data_description.lower()
    assert "report_id" in data_description
    assert "fallback" in data_description.lower()

    for tool_name in (
        "start_report_export",
        "get_report_export_file",
        "get_report_ai_job_export",
    ):
        description = SPECIAL_TOOL_DESCRIPTIONS[tool_name]
        assert "fallback" in description.lower() or "not default" in description.lower()


@pytest.mark.asyncio
async def test_report_ai_guidance_reaches_live_tool_descriptions():
    tools_by_name = {tool.name: tool for tool in await mcp.list_tools()}

    create_description = tools_by_name["create_report_ai_job"].description
    assert "get_report_ai_prompt_helper" in create_description
    assert "report_ai_prompt_helper" in create_description

    data_description = tools_by_name["get_report_ai_job_data"].description
    assert "limited=true" in data_description
    assert "report_id" in data_description
    assert "fallback" in data_description.lower()

    for tool_name in (
        "start_report_export",
        "get_report_export_file",
        "get_report_ai_job_export",
    ):
        description = tools_by_name[tool_name].description
        assert "fallback" in description.lower() or "not default" in description.lower()


def test_report_ai_goods_workaround_mentions_helper_tool_and_prompt():
    workaround = report_ai._report_ai_goods_good_id_workaround()
    steps_text = "\n".join(workaround["steps"])

    assert "get_report_ai_prompt_helper" in steps_text
    assert "report_ai_prompt_helper" in steps_text

    seeded_issue = next(
        issue
        for issue in SEED_ISSUES
        if issue.slug == "report-ai-goods-good-id-preview"
    )
    seeded_steps = "\n".join(seeded_issue.agent_playbook["steps"])
    assert "get_report_ai_prompt_helper" in seeded_steps
    assert "report_ai_prompt_helper" in seeded_steps


@pytest.mark.asyncio
@respx.mock
async def test_create_report_ai_job_posts_strict_intent_body():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "job": {"id": 10, "status": "queued", "candidates": None},
                    "is_deduplicated": False,
                },
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "create_report_ai_job",
            {"intent_text": "Покажи количество счетов за май 2026"},
        )

    assert route.call_count == 1
    assert _body_of(route) == {"intent_text": "Покажи количество счетов за май 2026"}
    payload = _structured(result)
    assert payload["data"]["is_deduplicated"] is False
    assert payload["data"]["job"]["status"] == "queued"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("intent_text", ["", "   ", "x" * 1001])
async def test_create_report_ai_job_rejects_empty_or_long_intent_before_upstream(intent_text):
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(200, json={"data": {"unexpected": True}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="intent_text"):
            await mcp.call_tool("create_report_ai_job", {"intent_text": intent_text})

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_exposes_candidates_for_confirmation():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "job": {
                        "id": 22,
                        "status": "needs_confirmation",
                        "candidates": [
                            {"report_id": 84, "title": "MCP existing", "match_score": 0.81}
                        ],
                    }
                },
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 22})

    assert route.call_count == 1
    candidates = _structured(result)["data"]["job"]["candidates"]
    assert candidates == [{"report_id": 84, "title": "MCP existing", "match_score": 0.81}]


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_adds_goods_good_id_workaround_for_preview_failed():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "job": {
                        "id": 22,
                        "status": "failed",
                        "error_code": "PREVIEW_FAILED",
                        "error_message_safe": "Unknown column 'good.id' in field list",
                    }
                },
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 22})

    assert route.call_count == 1
    job = _structured(result)["data"]["job"]
    assert job["mcp_workaround"]["code"] == "report_ai_goods_good_id_preview_failed"
    assert job["mcp_workaround"]["safe_to_retry"] is True
    assert "good.id" in job["mcp_workaround"]["do_not_do"][0]


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_does_not_annotate_unrelated_preview_failed():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "job": {
                        "id": 22,
                        "status": "failed",
                        "error_code": "PREVIEW_FAILED",
                        "error_message_safe": "Renderer timeout",
                    }
                },
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 22})

    assert "mcp_workaround" not in _structured(result)["data"]["job"]


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_status_poll_bypasses_get_cache():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "success": True,
                    "message": "",
                    "data": {"job": {"id": 22, "status": "queued"}},
                },
            ),
            httpx.Response(
                200,
                json={
                    "success": True,
                    "message": "",
                    "data": {"job": {"id": 22, "status": "ready_to_save"}},
                },
            ),
        ]
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        first = await mcp.call_tool("get_report_ai_job", {"job_id": 22})
        second = await mcp.call_tool("get_report_ai_job", {"job_id": 22})

    assert route.call_count == 2
    assert _structured(first)["data"]["job"]["status"] == "queued"
    assert _structured(second)["data"]["job"]["status"] == "ready_to_save"


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_adds_long_queued_diagnostics_metric_and_log(
    monkeypatch, caplog
):
    report_ai._reset_report_ai_queue_observations()
    service_metrics.reset_service_metrics()
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/77").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "job": {
                        "id": 77,
                        "status": "queued",
                        "created_at": "2026-06-18 12:00:00",
                        "updated_at": "2026-06-18 12:00:05",
                    }
                },
            },
        )
    )
    observed_times = iter([100.0, 131.0])
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: next(observed_times))

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch, caplog.at_level(logging.WARNING, logger="vetmanager.runtime"):
        first = await mcp.call_tool("get_report_ai_job", {"job_id": 77})
        second = await mcp.call_tool("get_report_ai_job", {"job_id": 77})

    assert route.call_count == 2
    assert "mcp_queue_diagnostics" not in _structured(first)["data"]["job"]
    diagnostics = _structured(second)["data"]["job"]["mcp_queue_diagnostics"]
    assert diagnostics["code"] == "report_ai_job_long_queued"
    assert diagnostics["observed_queued_age_seconds"] == 31
    assert diagnostics["threshold_seconds"] == 30
    assert diagnostics["status"] == "queued"
    assert diagnostics["created_at"] == "2026-06-18 12:00:00"
    assert diagnostics["updated_at"] == "2026-06-18 12:00:05"

    snapshot = service_metrics.snapshot_service_metrics()
    assert snapshot["report_ai_long_queued_polls_total"] == 1
    assert "vetmanager_report_ai_long_queued_polls_total 1" in (
        service_metrics.render_prometheus_metrics()
    )
    records = [
        record
        for record in caplog.records
        if getattr(record, "event_name", "") == "report_ai_job_long_queued"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.status == "queued"
    assert record.threshold_seconds == 30
    assert record.observed_queued_age_seconds == 31
    assert not hasattr(record, "intent_text")
    assert not hasattr(record, "domain")
    assert not hasattr(record, "sql")


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_fresh_queued_has_no_diagnostics_or_metric(monkeypatch):
    report_ai._reset_report_ai_queue_observations()
    service_metrics.reset_service_metrics()
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/78").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"job": {"id": 78, "status": "queued"}}},
        )
    )
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 200.0)

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 78})

    assert "mcp_queue_diagnostics" not in _structured(result)["data"]["job"]
    assert service_metrics.snapshot_service_metrics()["report_ai_long_queued_polls_total"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_queue_observation_is_tenant_scoped(monkeypatch):
    report_ai._reset_report_ai_queue_observations()
    service_metrics.reset_service_metrics()
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/77").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"job": {"id": 77, "status": "queued"}}},
        )
    )
    observed_times = iter([100.0, 131.0])
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: next(observed_times))

    tenant_a_headers, tenant_a_runtime = bearer_runtime_patch(
        scopes=(SCOPE_ANALYTICS_READ,),
    )
    tenant_b_headers, tenant_b_runtime = patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token-b",
        account_id=2,
        bearer_token_id=2,
        connection_id=2,
        scopes=(SCOPE_ANALYTICS_READ,),
    )
    with tenant_a_headers, tenant_a_runtime:
        await mcp.call_tool("get_report_ai_job", {"job_id": 77})
    with tenant_b_headers, tenant_b_runtime:
        tenant_b_first = await mcp.call_tool("get_report_ai_job", {"job_id": 77})

    assert route.call_count == 2
    assert "mcp_queue_diagnostics" not in _structured(tenant_b_first)["data"]["job"]
    assert service_metrics.snapshot_service_metrics()["report_ai_long_queued_polls_total"] == 0
    assert report_ai._report_ai_queue_observation_count() == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_clears_queued_observation_after_status_transition(monkeypatch):
    report_ai._reset_report_ai_queue_observations()
    service_metrics.reset_service_metrics()
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/79").mock(
        side_effect=[
            httpx.Response(200, json={"success": True, "data": {"job": {"id": 79, "status": "queued"}}}),
            httpx.Response(200, json={"success": True, "data": {"job": {"id": 79, "status": "ready_to_save"}}}),
            httpx.Response(200, json={"success": True, "data": {"job": {"id": 79, "status": "queued"}}}),
        ]
    )
    observed_times = iter([10.0, 45.0, 100.0])
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: next(observed_times))

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_report_ai_job", {"job_id": 79})
        await mcp.call_tool("get_report_ai_job", {"job_id": 79})
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 79})

    assert route.call_count == 3
    assert "mcp_queue_diagnostics" not in _structured(result)["data"]["job"]
    assert service_metrics.snapshot_service_metrics()["report_ai_long_queued_polls_total"] == 0


def test_report_ai_queue_observations_are_bounded_and_ttl_evicted():
    report_ai._reset_report_ai_queue_observations()
    report_ai._observe_report_ai_queue({"id": 1, "status": "queued"}, now=0.0)
    report_ai._observe_report_ai_queue(
        {"id": 2, "status": "queued"},
        now=report_ai.REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS + 1.0,
    )
    assert report_ai._report_ai_queue_observation_count() == 1

    report_ai._reset_report_ai_queue_observations()
    for job_id in range(report_ai.REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES + 2):
        report_ai._observe_report_ai_queue({"id": job_id, "status": "queued"}, now=0.0)

    assert (
        report_ai._report_ai_queue_observation_count()
        == report_ai.REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES
    )


@pytest.mark.asyncio
@respx.mock
async def test_confirm_report_ai_job_candidate_posts_strict_report_id_body():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/confirm").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "message": "", "data": {"report_id": 84}},
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "confirm_report_ai_job_candidate",
            {"job_id": 22, "report_id": 84},
        )

    assert route.call_count == 1
    assert _body_of(route) == {"report_id": 84}
    assert _structured(result)["data"]["report_id"] == 84


@pytest.mark.asyncio
@respx.mock
async def test_confirm_report_ai_job_candidate_preserves_validation_error_code():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/confirm").mock(
        return_value=httpx.Response(
            400,
            json={
                "success": False,
                "message": "report_id не входит в список предложенных кандидатов",
                "data": {"error_code": "VALIDATION_ERROR", "details": {}},
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="VALIDATION_ERROR"):
            await mcp.call_tool(
                "confirm_report_ai_job_candidate",
                {"job_id": 22, "report_id": 999},
            )

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_data_preserves_invalid_transition_error_code():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/22/data").mock(
        return_value=httpx.Response(
            409,
            json={
                "success": False,
                "message": "Данные доступны только для job со статусом saved или existing_report_matched",
                "data": {"error_code": "INVALID_TRANSITION", "details": {}},
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="INVALID_TRANSITION"):
            await mcp.call_tool("get_report_ai_job_data", {"job_id": 22})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_data_returns_limited_rows_metadata():
    billing_mock()
    rows = [{"ID Клиента": 1, "Баланс": "-1.00"}]
    route = respx.get(f"{BASE}/rest/api/report-ai-job/22/data").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "columns": ["ID Клиента", "Баланс"],
                    "rows": rows,
                    "total": 1001,
                    "limited": True,
                },
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_job_data", {"job_id": 22})

    assert route.call_count == 1
    payload = _structured(result)
    assert payload["data"]["rows"] == rows
    assert payload["data"]["total"] == 1001
    assert payload["data"]["limited"] is True


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_data_uses_short_cache_tier(monkeypatch):
    monkeypatch.setattr(vetmanager_client, "CACHE_TTL_SECONDS", 900.0)
    monkeypatch.setattr(vetmanager_client, "CACHE_TTL_SHORT_SECONDS", 0.01)
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/33/data").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "success": True,
                    "message": "",
                    "data": {
                        "columns": ["ID Клиента", "Баланс"],
                        "rows": [{"ID Клиента": 1, "Баланс": "-1.00"}],
                        "total": 1,
                        "limited": False,
                    },
                },
            ),
            httpx.Response(
                200,
                json={
                    "success": True,
                    "message": "",
                    "data": {
                        "columns": ["ID Клиента", "Баланс"],
                        "rows": [{"ID Клиента": 2, "Баланс": "0.00"}],
                        "total": 2,
                        "limited": False,
                    },
                },
            ),
        ]
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        first = await mcp.call_tool("get_report_ai_job_data", {"job_id": 33})
        await asyncio.sleep(0.02)
        second = await mcp.call_tool("get_report_ai_job_data", {"job_id": 33})

    assert route.call_count == 2
    assert _structured(first)["data"]["total"] == 1
    assert _structured(second)["data"]["total"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_save_report_ai_job_as_report_requires_report_ai_write_scope():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/save").mock(
        return_value=httpx.Response(200, json={"data": {"report_id": 84}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="report_ai.write"):
            await mcp.call_tool(
                "save_report_ai_job_as_report",
                {"job_id": 22, "title": "MCP debtors by negative balance 2026-06-15"},
            )

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_save_report_ai_job_as_report_rejects_analytics_write_without_report_ai_scope():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/save").mock(
        return_value=httpx.Response(200, json={"data": {"report_id": 84}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_WRITE,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="report_ai.write"):
            await mcp.call_tool(
                "save_report_ai_job_as_report",
                {"job_id": 22, "title": "MCP debtors by negative balance 2026-06-15"},
            )

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_save_report_ai_job_as_report_validates_meaningful_title_before_upstream():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/save").mock(
        return_value=httpx.Response(200, json={"data": {"report_id": 84}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="title"):
            await mcp.call_tool(
                "save_report_ai_job_as_report",
                {"job_id": 22, "title": "report"},
            )

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_save_report_ai_job_as_report_posts_title_and_surfaces_idempotency():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/save").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {"report_id": 84, "is_idempotent": True},
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "save_report_ai_job_as_report",
            {"job_id": 22, "title": "MCP debtors by negative balance 2026-06-15"},
        )

    assert route.call_count == 1
    assert _body_of(route) == {"title": "MCP debtors by negative balance 2026-06-15"}
    payload = _structured(result)
    assert payload["data"]["report_id"] == 84
    assert payload["data"]["is_idempotent"] is True


@pytest.mark.asyncio
@respx.mock
async def test_save_report_ai_job_as_report_preserves_invalid_transition_error_code():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/save").mock(
        return_value=httpx.Response(
            409,
            json={
                "success": False,
                "message": "Сохранение недоступно из статуса queued",
                "data": {"error_code": "INVALID_TRANSITION", "details": {}},
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="INVALID_TRANSITION"):
            await mcp.call_tool(
                "save_report_ai_job_as_report",
                {"job_id": 22, "title": "MCP queued report save check 2026-06-15"},
            )

    assert route.call_count == 1

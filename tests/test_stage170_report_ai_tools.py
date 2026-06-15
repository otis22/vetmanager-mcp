import json
import asyncio

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import SCOPE_ANALYTICS_READ, SCOPE_ANALYTICS_WRITE
import vetmanager_client


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch(*, scopes=(SCOPE_ANALYTICS_READ, SCOPE_ANALYTICS_WRITE)):
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        scopes=scopes,
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
async def test_save_report_ai_job_as_report_requires_write_scope():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/save").mock(
        return_value=httpx.Response(200, json={"data": {"report_id": 84}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="analytics.write"):
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

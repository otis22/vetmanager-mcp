"""Structured Report AI OTHER and the public invoice fallback contract."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from token_scopes import SCOPE_ANALYTICS_READ, SCOPE_FINANCE_READ
from tools.report_ai import _annotate_report_ai_workarounds


def _job(*, subtype="OTHER", status="failed", code="PREVIEW_FAILED",
         message="opaque upstream detail", workaround=None):
    job = {"id": 12, "status": status, "error_code": code,
           "error_message_safe": message}
    if subtype is not None:
        job["error_subtype"] = subtype
    if workaround is not None:
        job["mcp_workaround"] = workaround
    return job


def test_exact_other_gets_non_retry_invoice_workaround_without_raw_detail():
    job = _annotate_report_ai_workarounds({"data": {"job": _job()}})["data"]["job"]
    advice = job["mcp_workaround"]
    assert advice["code"] == "report_ai_upstream_preview_other"
    assert advice["failure_class"] == "upstream_preview_other"
    assert advice["safe_to_retry"] is False
    text = " ".join([advice["summary"], *advice["steps"], *advice["do_not_do"]])
    for required in ("get_invoices", "finance.read", "invoice_date_from",
                     "invoice_date_to", "status=exec", "limit=100", "offset=0",
                     "id", "totalCount", "clinic_id", "incomplete", "Decimal",
                     '"operator":">"', '"direction":"ASC"'):
        assert required in text
    assert "StartReport" in text and "retry" in text.lower()
    assert "Only if the original request was branch revenue" in text
    assert "For any other report purpose" in text
    assert "opaque upstream detail" not in str(job)


@pytest.mark.parametrize("overrides", [
    {"subtype": None}, {"subtype": "OTHER_ERROR"},
    {"status": "ready_to_save"}, {"code": "OTHER"},
])
def test_other_classifier_requires_exact_structured_fields(overrides):
    job = _annotate_report_ai_workarounds({"data": {"job": _job(**overrides)}})["data"]["job"]
    assert job.get("mcp_workaround", {}).get("code") != "report_ai_upstream_preview_other"


def test_existing_workaround_is_preserved():
    previous = {"code": "existing", "safe_to_retry": False}
    job = _annotate_report_ai_workarounds(
        {"data": {"job": _job(workaround=previous)}}
    )["data"]["job"]
    assert job["mcp_workaround"] == previous


@pytest.mark.parametrize("message,expected_code", [
    ("SQLSTATE syntax error good_tag", "report_ai_combination_sql_preview_failed"),
    ("curl error: 28", "report_ai_upstream_preview_other"),
    ("Unknown column good.id", "report_ai_upstream_preview_other"),
])
def test_non_retry_other_wins_over_retry_heuristics_but_not_combination(message, expected_code):
    job = _annotate_report_ai_workarounds(
        {"data": {"job": _job(message=message)}}
    )["data"]["job"]
    assert job["mcp_workaround"]["code"] == expected_code
    assert job["mcp_workaround"]["safe_to_retry"] is False
    assert message not in str(job)


@pytest.mark.asyncio
@respx.mock
async def test_public_job_path_adds_other_workaround():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/12").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": _job()}})
    )
    headers, runtime = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 12})
    assert route.call_count == 1
    assert result.structured_content["data"]["job"]["mcp_workaround"]["safe_to_retry"] is False
    assert "opaque upstream detail" not in str(result.structured_content)


@pytest.mark.asyncio
@respx.mock
async def test_public_invoice_tool_accepts_keyset_filter_and_preserves_total_count():
    billing_mock()
    seen = []

    def page(request):
        query = parse_qs(urlparse(str(request.url)).query)
        seen.append(query)
        filters = json.loads(query["filter"][0])
        cursor = next((int(f["value"]) for f in filters if f["property"] == "id"), 0)
        rows = [
            {"id": i, "clinic_id": 1 if i % 2 else 2, "status": "exec",
             "invoice_date": "2026-11-12 10:00:00", "amount": "1.00"}
            for i in range(cursor + 1, min(cursor + 101, 102))
        ]
        return httpx.Response(200, json={"success": True, "data": {
            "invoice": rows, "totalCount": 101 - cursor,
        }})

    route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=page)
    headers, runtime = bearer_runtime_patch(scopes=(SCOPE_FINANCE_READ,))
    base = {"limit": 100, "offset": 0, "status": "exec",
            "invoice_date_from": "2026-11-12", "invoice_date_to": "2026-11-12",
            "sort": [{"property": "id", "direction": "ASC"}]}
    with headers, runtime:
        first = (await mcp.call_tool("get_invoices", base)).structured_content["data"]
        second = (await mcp.call_tool("get_invoices", {
            **base, "filter": [{"property": "id", "operator": ">", "value": 100}],
        })).structured_content["data"]
    assert route.call_count == 2
    assert len(first["invoice"]) == 100 and first["totalCount"] == 101
    assert [row["id"] for row in second["invoice"]] == [101]
    assert second["totalCount"] == 1
    assert all(query["offset"] == ["0"] and query["limit"] == ["100"] for query in seen)
    assert all(json.loads(query["sort"][0]) == base["sort"] for query in seen)
    for index, query in enumerate(seen):
        filters = json.loads(query["filter"][0])
        assert {item["property"] for item in filters} == (
            {"status", "invoice_date"} | ({"id"} if index else set())
        )
        assert any(item["property"] == "status" and item["value"] == "exec"
                   for item in filters)
        assert {item["operator"] for item in filters if item["property"] == "invoice_date"} == {">=", "<"}
        if index:
            assert any(item == {"property": "id", "operator": ">", "value": 100}
                       for item in filters)

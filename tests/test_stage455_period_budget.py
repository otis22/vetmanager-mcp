"""Stage 455: a full period scan is bounded by 1000 GETs and 1800 seconds."""

import pytest

import tools.finance as finance
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


def test_default_period_budget_is_thousand():
    assert finance._INVOICE_DOCUMENT_PERIOD_CALL_BUDGET == 1000


async def _call():
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime:
        result = await mcp.call_tool("get_invoice_documents_by_period", {
            "date_from": "2026-09-12", "date_to": "2026-09-12", "limit": 1,
        })
    return result.structured_content["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("document_pages", [25, 999])
async def test_period_completes_past_twenty_including_exact_thousand(monkeypatch, document_pages):
    calls = []

    async def listing(path, *, offset=0, **kwargs):
        calls.append(path)
        if path == "/rest/api/invoice":
            return {"success": True, "data": {"invoice": [{"id": 1, "invoice_date": "2026-09-12 10:00:00"}],
                             "totalCount": 1}}
        rows = [{"id": i, "document_id": 1} for i in range(offset + 1, offset + 2)]
        return {"success": True, "data": {"invoiceDocument": rows, "totalCount": document_pages}}

    monkeypatch.setattr(finance, "crud_list", listing)
    data = await _call()
    assert data["limited"] is False
    assert data["totalCount"] == document_pages
    assert len(data["invoiceDocument"]) == 1
    assert len(calls) == document_pages + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exhaust_on", ["invoice", "invoiceDocument"])
async def test_both_period_loops_stop_before_get_1001(monkeypatch, exhaust_on):
    calls = []

    async def listing(path, *, offset=0, **kwargs):
        calls.append(path)
        if path == "/rest/api/invoice":
            if exhaust_on != "invoice":
                return {"success": True, "data": {"invoice": [{"id": 1, "invoice_date": "2026-09-12 10:00:00"}],
                                 "totalCount": 1}}
            rows = [{"id": i, "invoice_date": "2026-09-12 10:00:00"}
                    for i in range(offset + 1, offset + 2)]
            return {"success": True, "data": {"invoice": rows, "totalCount": 1001}}
        rows = [{"id": i, "document_id": 1} for i in range(offset + 1, offset + 2)]
        return {"success": True, "data": {"invoiceDocument": rows, "totalCount": 1000}}

    monkeypatch.setattr(finance, "crud_list", listing)
    data = await _call()
    assert len(calls) == 1000
    assert data["limited"] is True
    assert data["limited_reason"] == "upstream_call_budget"
    assert data["upstream_calls"] == 1000
    assert data["invoiceDocument"] == []
    assert data["totalCount"] is None and data["next_offset"] is None


@pytest.mark.asyncio
async def test_period_time_budget_allows_thirty_minutes_and_does_not_start_late_get(monkeypatch):
    clock = [0.0]
    calls = []

    async def listing(path, **kwargs):
        calls.append(path)
        clock[0] += 900
        if path == "/rest/api/invoice":
            return {"success": True, "data": {"invoice": [{"id": 1, "invoice_date": "2026-09-12 10:00:00"}],
                             "totalCount": 1}}
        return {"success": True, "data": {"invoiceDocument": [{"id": i, "document_id": 1}
                                              for i in range(1, 101)], "totalCount": 101}}

    monkeypatch.setattr(finance, "monotonic", lambda: clock[0], raising=False)
    monkeypatch.setattr(finance, "crud_list", listing)
    data = await _call()
    assert clock[0] == 1800
    assert len(calls) == 2
    assert data["limited"] is True and data["limited_reason"] == "time_budget"
    assert data["upstream_calls"] == 2
    assert data["invoiceDocument"] == [] and data["next_offset"] is None

"""Bounded daily aggregate: privacy, completeness, and access guards."""

from unittest.mock import AsyncMock
from datetime import date as Date
import json

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


async def _call(args, *, scopes=None):
    options = {} if scopes is None else {"scopes": scopes}
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1, **options,
    )
    with headers, runtime:
        return (await mcp.call_tool("get_admissions_daily_summary", args)).structured_content


@pytest.mark.asyncio
async def test_daily_summary_bounded_and_no_personal_rows(monkeypatch):
    import tools.admission as admission

    async def page(_path, *, limit, offset, **_kwargs):
        assert limit == 100
        rows = [{"id": offset + i + 1, "status": "save" if i % 2 else "accepted",
                 "client": {"cell_phone": "+7 999 123 45 67"}, "description": "secret"}
                for i in range(100)]
        return {"success": True, "data": {"admission": rows, "totalCount": 600}}

    mock = AsyncMock(side_effect=page)
    monkeypatch.setattr(admission, "crud_list", mock)
    result = await _call({"date": "2026-10-16"})
    assert mock.await_count == 5
    assert result["processed_count"] == 500
    assert result["total_count"] == 600
    assert result["truncated"] is True and result["complete"] is False
    assert result["status_counts"] == {"accepted": 250, "save": 250}
    assert len(json.dumps(result).encode()) < 1000
    assert not any(key in result for key in ("admission", "client", "description", "rows"))
    assert "+7 999" not in str(result)


@pytest.mark.asyncio
async def test_daily_summary_complete_and_scope(monkeypatch):
    import tools.admission as admission
    mock = AsyncMock(return_value={"success": True, "data": {
        "admission": [{"id": 1, "status": "save"}], "totalCount": 1,
    }})
    monkeypatch.setattr(admission, "crud_list", mock)
    result = await _call({"date": "2026-10-16"})
    assert result["processed_count"] == 1
    assert result["complete"] is True and result["truncated"] is False
    assert mock.await_count == 1
    mock.reset_mock()
    with pytest.raises(Exception):
        await _call({"date": "2026-10-16"}, scopes=())
    mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_daily_summary_registered_and_visible():
    from tool_access_registry import TOOL_REQUIRED_SCOPES
    from tool_scope_security import visible_tools_for_scopes
    assert "get_admissions_daily_summary" in TOOL_REQUIRED_SCOPES
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert "get_admissions_daily_summary" in names
    assert "get_admissions_daily_summary" not in {
        tool.name for tool in visible_tools_for_scopes(tools, ())
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["duplicate", "failed_page", "premature_empty"])
async def test_daily_summary_fails_closed_on_page_drift(monkeypatch, failure):
    import tools.admission as admission

    async def page(_path, *, offset, **_kwargs):
        if offset == 0:
            return {"success": True, "data": {"admission": [
                {"id": i + 1, "status": "save"} for i in range(100)
            ], "totalCount": 150}}
        if failure == "failed_page":
            return {"success": False, "message": "upstream error"}
        if failure == "premature_empty":
            return {"success": True, "data": {"admission": [], "totalCount": 150}}
        return {"success": True, "data": {"admission": [
            {"id": i + 1, "status": "save"} for i in range(50)
        ], "totalCount": 150}}

    monkeypatch.setattr(admission, "crud_list", AsyncMock(side_effect=page))
    with pytest.raises(Exception, match="Daily summary"):
        await _call({"date": "2026-10-16"})


@pytest.mark.asyncio
async def test_daily_summary_unknown_total_and_status_bucket(monkeypatch):
    import tools.admission as admission
    mock = AsyncMock(return_value={"success": True, "data": {"admission": [
        {"id": 1, "status": "person@example.test"},
    ]}})
    monkeypatch.setattr(admission, "crud_list", mock)
    result = await _call({"date": "2026-10-16"})
    assert result["total_count"] is None
    assert result["complete"] is True
    assert result["status_counts"] == {"other": 1}
    assert "person@example.test" not in str(result)


@pytest.mark.asyncio
async def test_daily_summary_uses_clinic_day_and_filter(monkeypatch):
    import tools.admission as admission
    today = AsyncMock(return_value=Date(2026, 10, 17))
    mock = AsyncMock(return_value={"success": True, "data": {
        "admission": [], "totalCount": 0,
    }})
    monkeypatch.setattr(admission, "clinic_local_today", today)
    monkeypatch.setattr(admission, "crud_list", mock)
    result = await _call({"date": "today", "clinic_id": 7})
    today.assert_awaited_once_with(7, relative=True)
    assert result["date"] == "2026-10-17"
    assert any(item.property == "clinic_id" for item in mock.call_args.kwargs["filters"])


@pytest.mark.asyncio
async def test_daily_summary_rejects_contradictory_more_flag(monkeypatch):
    import tools.admission as admission
    monkeypatch.setattr(admission, "crud_list", AsyncMock(return_value={
        "success": True, "data": {"admission": [{"id": 1, "status": "save"}],
                                  "has_more": True},
    }))
    with pytest.raises(Exception, match="Daily summary"):
        await _call({"date": "2026-10-16"})


@pytest.mark.asyncio
@pytest.mark.parametrize("later_total", ["missing", None])
async def test_daily_summary_rejects_total_metadata_drift(monkeypatch, later_total):
    import tools.admission as admission

    async def page(_path, *, offset, **_kwargs):
        return {"success": True, "data": {
            "admission": [{"id": offset + i + 1, "status": "save"}
                          for i in range(100 if offset == 0 else 1)],
            **({"totalCount": 101} if offset == 0 else
               {} if later_total == "missing" else {"totalCount": None}),
        }}

    monkeypatch.setattr(admission, "crud_list", AsyncMock(side_effect=page))
    with pytest.raises(Exception, match="Daily summary"):
        await _call({"date": "2026-10-16"})

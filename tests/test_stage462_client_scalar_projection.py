"""Stage 462: a documented client relation must not break scalar projection."""

from unittest.mock import AsyncMock

import pytest

from exceptions import ToolInputError
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


CLIENT_ROW = {
    "id": 101, "status": "ACTIVE", "client_type_data": {},
    "city_data": {}, "registration_index": None,
    "cell_phone": "+7 999 123-45-67",
}


async def _call(tool, arguments, *, depersonalized=False):
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1, is_depersonalized=depersonalized,
    )
    with headers, runtime:
        return (await mcp.call_tool(tool, arguments)).structured_content


@pytest.mark.asyncio
@pytest.mark.parametrize("depersonalized", [False, True])
async def test_confirmed_client_shape_keeps_scalar_pages(monkeypatch, depersonalized):
    async def page(_path, *, limit, offset, **_kwargs):
        assert limit == 1
        assert offset in (0, 1)
        return {"success": True, "message": "", "data": {
            "client": [{**CLIENT_ROW, "id": 101 + offset}], "totalCount": 2,
        }, "limit": limit, "offset": offset}

    mocked = AsyncMock(side_effect=page)
    monkeypatch.setattr("tools.client.crud_list", mocked)
    for offset in (0, 1):
        body = await _call("get_clients", {
            "limit": 1, "offset": offset, "fields": ["id", "status"],
            "include": [], "mask_contacts": True,
        }, depersonalized=depersonalized)
        assert body["success"] is True
        assert body["message"] == ""
        assert body["limit"] == 1 and body["offset"] == offset
        assert body["data"]["totalCount"] == 2
        assert body["data"]["client"] == [{"id": 101 + offset, "status": "ACTIVE"}]
    assert mocked.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", [{}, None])
async def test_confirmed_relation_object_or_null_is_omitted(monkeypatch, relation):
    row = {**CLIENT_ROW, "client_type_data": relation}
    monkeypatch.setattr("tools.client.crud_list", AsyncMock(return_value={
        "success": True, "data": {"client": [row], "totalCount": 1},
    }))
    for args in ({"fields": ["id", "status"], "include": []},
                 {"compact": True, "include": []},
                 {"include": []},
                 {"fields": ["id", "status"]}):
        result = await _call("get_clients", {"limit": 1, **args})
        projected = result["data"]["client"][0]
        assert "client_type_data" not in projected
        if args.get("fields"):
            assert set(projected) == {"id", "status"}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["unexpected", 7, True, []])
async def test_client_type_relation_requires_object_or_null(monkeypatch, invalid):
    monkeypatch.setattr("tools.client.crud_list", AsyncMock(return_value={
        "success": True, "data": {"client": [{**CLIENT_ROW, "client_type_data": invalid}],
                                  "totalCount": 1},
    }))
    with pytest.raises(Exception, match="Projection"):
        await _call("get_clients", {"fields": ["id", "status"], "include": []})


@pytest.mark.asyncio
async def test_unknown_relation_still_fails_closed(monkeypatch):
    monkeypatch.setattr("tools.client.crud_list", AsyncMock(return_value={
        "success": True, "data": {"client": [{**CLIENT_ROW, "new_relation": {}}],
                                  "totalCount": 1},
    }))
    with pytest.raises(Exception, match="Projection found an unrecognized nested field"):
        await _call("get_clients", {"fields": ["id", "status"], "include": []})


@pytest.mark.asyncio
async def test_neighbor_tool_does_not_accept_client_type_relation(monkeypatch):
    monkeypatch.setattr("tools.admission.crud_list", AsyncMock(return_value={
        "success": True, "data": {"admission": [{"id": 1, "client_type_data": {}}],
                                  "totalCount": 1},
    }))
    monkeypatch.setattr("tools.admission.clinic_local_today", AsyncMock(return_value=None))
    with pytest.raises(Exception, match="Projection found an unrecognized nested field"):
        await _call("get_admissions", {"include": []})


@pytest.mark.asyncio
@pytest.mark.parametrize("argument, message", [
    ("fields", "Unknown or nested fields"),
    ("include", "Unknown include relations"),
], ids=["fields", "include"])
async def test_hidden_relation_is_not_publicly_selectable(monkeypatch, argument, message):
    mocked = AsyncMock(return_value={"success": True, "data": {"client": [], "totalCount": 0}})
    monkeypatch.setattr("tools.client.crud_list", mocked)
    args = {argument: ["client_type_data"]}
    with pytest.raises(ToolInputError, match=message):
        await _call("get_clients", args)
    mocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_response_and_mask_only_keep_previous_behavior(monkeypatch):
    monkeypatch.setattr("tools.client.crud_list", AsyncMock(return_value={
        "success": True, "data": {"client": [CLIENT_ROW], "totalCount": 1},
    }))
    full = await _call("get_clients", {"limit": 1})
    assert full["data"]["client"][0]["client_type_data"] == {}
    with pytest.raises(Exception, match="Projection found an unrecognized nested field"):
        await _call("get_clients", {"limit": 1, "mask_contacts": True})

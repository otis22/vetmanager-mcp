"""Stage 337: a named empty staff search explains the safe next step."""

import pytest
from fastmcp.exceptions import ToolError

from depersonalization import sanitize_tool_result
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from tool_descriptions import compose_tool_description


def _runtime_patch(*, is_depersonalized: bool = False):
    return patch_runtime_credentials(
        "testclinic",
        "test-key-mock",
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        is_depersonalized=is_depersonalized,
    )


@pytest.mark.asyncio
async def test_empty_named_user_search_returns_complete_hint(monkeypatch):
    import tools.user as user_module

    async def empty_page(*args, **kwargs):
        return ([], 0)

    monkeypatch.setattr(user_module, "paginate_all", empty_page)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_users", {"name": "Ионова"})

    payload = result.structured_content
    assert payload["data"]["totalCount"] == 0
    hint = payload["mcp_hint"]
    assert set(hint) == {"code", "summary", "steps", "do_not_do"}
    assert hint["code"] == "user_name_search_empty"
    assert "3–4" in " ".join(hint["steps"])
    assert "first_name" in " ".join(hint["steps"])
    assert "position_id" in " ".join(hint["steps"])
    assert "get_user_by_id" in " ".join(hint["steps"])
    assert "as recorded" in " ".join(hint["steps"]).lower()
    assert "inactive" in " ".join(hint["do_not_do"]).lower()
    assert "is_active=None" in " ".join(hint["do_not_do"])


@pytest.mark.asyncio
async def test_nonempty_named_user_search_has_no_hint(monkeypatch):
    import tools.user as user_module

    async def one_user(*args, **kwargs):
        return ([{"id": 7, "last_name": "Иванова", "position_id": 3}], 1)

    monkeypatch.setattr(user_module, "paginate_all", one_user)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_users", {"name": "Иванова"})

    payload = result.structured_content
    assert payload["data"]["totalCount"] == 1
    assert "mcp_hint" not in payload


@pytest.mark.asyncio
async def test_user_search_without_name_has_no_hint(monkeypatch):
    import tools.user as user_module

    async def empty_list(*args, **kwargs):
        return {"success": True, "data": {"user": [], "totalCount": 0}}

    monkeypatch.setattr(user_module, "crud_list", empty_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_users", {})

    assert "mcp_hint" not in result.structured_content


@pytest.mark.asyncio
async def test_named_user_search_exception_has_no_synthetic_response(monkeypatch):
    import tools.user as user_module

    async def fail(*args, **kwargs):
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(user_module, "paginate_all", fail)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch, pytest.raises(ToolError, match="upstream failed"):
        await mcp.call_tool("get_users", {"name": "Ионова"})


def test_user_name_hint_survives_depersonalization_without_affecting_placeholders():
    hint = {
        "code": "user_name_search_empty",
        "summary": "No staff member matched the supplied name.",
        "steps": ["Repeat with a 3–4 letter surname stem."],
        "do_not_do": ["Do not conclude that the doctor is inactive."],
    }
    payload = {
        "data": {"user": [{"id": 7, "last_name": "Иванова"}], "totalCount": 1},
        "mcp_hint": hint,
    }

    sanitized = sanitize_tool_result(payload, tool_name="get_users")

    assert sanitized["mcp_hint"] == hint
    assert sanitized["data"]["user"][0]["last_name"] == "[user:7:last_name]"


def test_get_users_description_points_to_empty_search_hint_without_copying_steps():
    description = compose_tool_description("get_users") or ""

    assert "mcp_hint" in description
    assert "surname stem" in description
    assert "3–4" not in description
    assert "get_user_by_id" not in description

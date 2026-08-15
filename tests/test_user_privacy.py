"""Privacy regressions for user read tools."""

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


_UPSTREAM_USER = {
    "id": 7,
    "last_name": "Иванова",
    "first_name": "Анна",
    "middle_name": "Сергеевна",
    "nickname": "anna",
    "position_id": 3,
    "role_id": 4,
    "is_active": 1,
    "login": "anna.admin",
    "passwd": "0123456789abcdef0123456789abcdef",
    "last_change_pwd_date": "2026-08-01",
    "email": "anna@example.test",
    "phone": "+74950000000",
    "cell_phone": "+79990000000",
    "address": "ул. Пример, 1",
    "user_inn": "123456789012",
    "calc_percents": 25,
    "future_sensitive_field": "must not leak",
}

_ANALYTICS_FIELDS = {
    "id",
    "last_name",
    "first_name",
    "middle_name",
    "nickname",
    "position_id",
    "role_id",
    "is_active",
}


def _runtime_patch():
    return patch_runtime_credentials(
        "testclinic",
        "test-key-mock",
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _assert_analytics_projection(user: dict) -> None:
    assert set(user) == _ANALYTICS_FIELDS
    assert user["id"] == _UPSTREAM_USER["id"]
    assert user["last_name"] == _UPSTREAM_USER["last_name"]
    assert user["position_id"] == _UPSTREAM_USER["position_id"]
    assert user["role_id"] == _UPSTREAM_USER["role_id"]
    assert user["is_active"] == _UPSTREAM_USER["is_active"]
    assert "login" not in user
    assert "passwd" not in user


@pytest.mark.asyncio
async def test_get_users_returns_only_analytics_fields(monkeypatch):
    import tools.user as user_module

    async def fake_crud_list(*args, **kwargs):
        return {"success": True, "data": {"user": [_UPSTREAM_USER], "totalCount": 1}}

    monkeypatch.setattr(user_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_users", {})

    payload = result.structured_content or {}
    assert payload["data"]["totalCount"] == 1
    _assert_analytics_projection(payload["data"]["user"][0])


@pytest.mark.asyncio
async def test_get_users_name_search_projects_merged_records(monkeypatch):
    import tools.user as user_module

    async def fake_crud_list(*args, **kwargs):
        return {"success": True, "data": {"user": [_UPSTREAM_USER], "totalCount": 1}}

    monkeypatch.setattr(user_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_users", {"name": "Иванова"})

    payload = result.structured_content or {}
    assert payload["data"]["totalCount"] == 1
    _assert_analytics_projection(payload["data"]["user"][0])


@pytest.mark.asyncio
async def test_get_user_by_id_returns_only_analytics_fields(monkeypatch):
    import tools.user as user_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {"success": True, "data": _UPSTREAM_USER}

    monkeypatch.setattr(user_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_user_by_id", {"user_id": 7})

    payload = result.structured_content or {}
    _assert_analytics_projection(payload["data"])


@pytest.mark.asyncio
async def test_update_user_returns_only_analytics_fields(monkeypatch):
    import tools.user as user_module

    async def fake_crud_update(*args, **kwargs):
        return {"success": True, "data": _UPSTREAM_USER}

    monkeypatch.setattr(user_module, "crud_update", fake_crud_update)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_user", {"user_id": 7, "last_name": "Иванова"})

    payload = result.structured_content or {}
    _assert_analytics_projection(payload["data"])


def test_user_projection_preserves_error_envelope_without_data():
    from tools.user import _project_user_response

    upstream = {
        "success": False,
        "errors": [{"code": "UPSTREAM_FAILURE", "detail": "try later"}],
        "hint": "retry",
    }

    projected = _project_user_response(upstream)

    assert projected == upstream
    assert "data" not in projected


def test_user_projection_preserves_non_user_data_envelope():
    from tools.user import _project_user_response

    upstream = {
        "success": False,
        "data": {"error_code": "UPSTREAM_FAILURE", "retry_after": 30},
        "errors": ["request failed"],
        "hint": "retry",
    }

    assert _project_user_response(upstream) == upstream

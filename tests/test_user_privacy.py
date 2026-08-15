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


def test_user_projection_preserves_non_user_error_data_and_logs_anomaly(caplog):
    from tools.user import _project_user_response

    upstream = {
        "success": False,
        "data": {"error_code": "UPSTREAM_FAILURE", "retry_after": 30},
        "errors": ["request failed"],
        "hint": "retry",
    }

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        projected = _project_user_response(upstream)

    assert projected == upstream
    assert any(
        record.message == "user_projection_unexpected_data_shape"
        and record.event_name == "user_projection_unexpected_data_shape"
        for record in caplog.records
    )


def test_user_projection_sanitizes_nested_records_and_logs_unexpected_data_shape(caplog):
    from tools.user import _project_user_response

    upstream = {
        "success": True,
        "data": {"staff": [{"first_name": "Анна", "passwd": "secret"}]},
        "hint": "unexpected upstream wrapper",
    }

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        projected = _project_user_response(upstream)

    assert projected["hint"] == upstream["hint"]
    assert projected["data"] == {"staff": [{"first_name": "Анна"}]}
    assert any(
        record.message == "user_projection_unexpected_data_shape"
        and record.event_name == "user_projection_unexpected_data_shape"
        for record in caplog.records
    )


def test_user_projection_allows_sparse_direct_record_without_id():
    from tools.user import _project_user_response

    projected = _project_user_response(
        {"success": True, "data": {"first_name": "Анна", "passwd": "secret"}}
    )

    assert projected["data"] == {"first_name": "Анна"}


def test_user_projection_keeps_only_verified_total_count_metadata():
    from tools.user import _project_user_response

    projected = _project_user_response(
        {
            "success": True,
            "data": {
                "user": [_UPSTREAM_USER],
                "totalCount": 1,
                "pageSize": 20,
            },
        },
    )

    assert set(projected["data"]) == {"user", "totalCount"}
    _assert_analytics_projection(projected["data"]["user"][0])


def test_user_projection_sanitizes_error_user_payload_without_losing_envelope():
    from tools.user import _project_user_response

    upstream = {
        "success": False,
        "message": "partial failure",
        "data": {"totalCount": 1, "user": [_UPSTREAM_USER]},
        "errors": [{"code": "UPSTREAM_FAILURE"}],
        "hint": "retry",
    }

    projected = _project_user_response(upstream)

    assert projected["success"] is False
    assert projected["message"] == upstream["message"]
    assert projected["errors"] == upstream["errors"]
    assert projected["hint"] == upstream["hint"]
    assert projected["data"]["totalCount"] == 1
    _assert_analytics_projection(projected["data"]["user"][0])


def test_user_projection_keeps_total_count_in_unexpected_data_shape(caplog):
    from tools.user import _project_user_response

    upstream = {
        "success": True,
        "data": {"totalCount": 1, "staff": [_UPSTREAM_USER]},
    }

    with caplog.at_level("WARNING", logger="vetmanager.runtime"):
        projected = _project_user_response(upstream)

    assert projected["data"]["totalCount"] == 1
    _assert_analytics_projection(projected["data"]["staff"][0])
    assert any(
        record.message == "user_projection_unexpected_data_shape"
        for record in caplog.records
    )

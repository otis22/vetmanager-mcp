"""Stage 356: a sale option changes only after a fresh, matching preview."""

import json

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import SCOPE_INVENTORY_WRITE
from tool_access_registry import TOOL_REQUIRED_SCOPES, TOKEN_PRESET_SCOPES
from tool_scope_security import visible_tools_for_scopes


BASE = "https://testclinic.vetmanager.cloud"
ROW = {"id": 38, "good_id": 34, "clinic_id": 1, "unit_sale_id": 4,
       "status": "active", "price": "2100.0000000000"}
GOOD = {"id": 34, "title": "Тестовый товар", "is_for_sale": 1, "is_active": 1}


def mocks(*, status="active"):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}}))
    state = {"status": status, "row": dict(ROW)}

    def read(_request):
        return httpx.Response(200, json={"data": {"goodSaleParam":
                                      dict(state["row"], status=state["status"])}})

    def write(request):
        payload = json.loads(request.content)
        assert list(payload) == ["status"], "writer must not touch price or sibling fields"
        state["status"] = payload["status"]
        return read(request)

    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(side_effect=read)
    respx.get(f"{BASE}/rest/api/good/34").mock(
        return_value=httpx.Response(200, json={"data": {"good": GOOD}}))
    respx.get(f"{BASE}/rest/api/clinics/1").mock(
        return_value=httpx.Response(200, json={"data": {"clinics": {
            "id": 1, "title": "Тестовая клиника"}}}))
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(
        return_value=httpx.Response(200, json={"data": {
            "goodSaleParam": [dict(ROW, status=status)], "totalCount": 1}}))
    return state, respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(side_effect=write)


async def call(**args):
    headers, runtime = patch_runtime_credentials("testclinic", "test-secret")
    with headers, runtime:
        result = await mcp.call_tool("set_good_sale_param_status", args)
    return result.structured_content


@pytest.mark.asyncio
@respx.mock
async def test_preview_is_read_only_and_confirmation_is_bound_to_row():
    state, put = mocks()
    preview = await call(sale_param_id=38, clinic_id=1, target_status="disabled")
    assert preview["applied"] is False
    assert preview["good"]["id"] == 34
    assert preview["clinic_id"] == 1
    assert preview["clinic"]["title"] == "Тестовая клиника"
    assert preview["current_status"] == "active"
    assert preview["target_status"] == "disabled"
    assert preview["last_active_sale_option"] is True
    assert put.call_count == 0

    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled", confirm=True)
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=2, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=1, target_status="active",
                   confirm=True, confirmation=preview["confirmation"])
    assert put.call_count == 0

    applied = await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                         confirm=True, confirmation=preview["confirmation"])
    assert applied["applied"] is True
    assert applied["after"] == "disabled"
    assert state["status"] == "disabled"
    assert put.call_count == 1

    repeat = await call(sale_param_id=38, clinic_id=1, target_status="disabled")
    unchanged = await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                           confirm=True, confirmation=repeat["confirmation"])
    assert unchanged["applied"] is False
    assert put.call_count == 1

    restored = await call(sale_param_id=38, clinic_id=1, target_status="active")
    answer = await call(sale_param_id=38, clinic_id=1, target_status="active",
                        confirm=True, confirmation=restored["confirmation"])
    assert answer["after"] == "active"
    assert state["status"] == "active"


@pytest.mark.asyncio
@respx.mock
async def test_foreign_clinic_unknown_status_and_changed_snapshot_never_write():
    state, put = mocks()
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=2, target_status="disabled")
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=1, target_status="archived")
    state["status"] = "archived"
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled")
    state["status"] = "active"
    preview = await call(sale_param_id=38, clinic_id=1, target_status="disabled")
    state["row"]["price"] = "2200.0000000000"
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_expired_and_future_confirmation_never_write(monkeypatch):
    _, put = mocks()
    monkeypatch.setattr("tools.warehouse.time.time", lambda: 1_000_000)
    preview = await call(sale_param_id=38, clinic_id=1, target_status="disabled")
    monkeypatch.setattr("tools.warehouse.time.time", lambda: 1_000_601)
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])
    monkeypatch.setattr("tools.warehouse.time.time", lambda: 999_999)
    with pytest.raises(Exception):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_write_failure_and_mismatched_readback_are_explicit():
    _, put = mocks()
    preview = await call(sale_param_id=38, clinic_id=1, target_status="disabled")
    put.mock(return_value=httpx.Response(503, json={"success": False}))
    with pytest.raises(Exception, match="outcome is unknown"):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])

    put.mock(return_value=httpx.Response(200, json={"success": True}))
    with pytest.raises(Exception, match="readback differs"):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_change_between_check_and_put_is_reported():
    state, put = mocks()
    preview = await call(sale_param_id=38, clinic_id=1, target_status="disabled")

    def concurrent_write(_request):
        state["row"]["price"] = "2200.0000000000"
        state["status"] = "disabled"
        return httpx.Response(201, json={"success": True})

    put.mock(side_effect=concurrent_write)
    with pytest.raises(Exception, match="readback differs"):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])
    assert put.call_count == 1


def test_write_scope_is_visible_only_to_inventory_presets():
    name = "set_good_sale_param_status"
    assert TOOL_REQUIRED_SCOPES[name] == (SCOPE_INVENTORY_WRITE,)
    assert SCOPE_INVENTORY_WRITE in TOKEN_PRESET_SCOPES["inventory"]
    assert SCOPE_INVENTORY_WRITE not in TOKEN_PRESET_SCOPES["read_only"]

    class Tool:
        def __init__(self):
            self.name = name
            self.meta = {"securitySchemes": [{"type": "oauth2", "scopes": [SCOPE_INVENTORY_WRITE]}]}

    assert visible_tools_for_scopes([Tool()], TOKEN_PRESET_SCOPES["inventory"])
    assert not visible_tools_for_scopes([Tool()], TOKEN_PRESET_SCOPES["read_only"])

    from web_html import render_access_summary
    from web_html import TOKEN_PRESET_DISPLAY_LABELS
    assert "Номенклатура" in TOKEN_PRESET_DISPLAY_LABELS["inventory"]
    assert "номенклатура" in render_access_summary("inventory")


@pytest.mark.asyncio
@respx.mock
async def test_read_only_key_cannot_even_preview_the_writer():
    _, put = mocks()
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-secret", scopes=TOKEN_PRESET_SCOPES["read_only"])
    with headers, runtime:
        with pytest.raises(Exception):
            await mcp.call_tool("set_good_sale_param_status", {
                "sale_param_id": 38, "clinic_id": 1, "target_status": "disabled"})
    assert put.call_count == 0
    assert not respx.calls, "the access check must run before REST"


def test_visual_evidence_shows_inventory_key_issuance():
    from scripts.capture_visual_matrix import _pages, required_scenes

    assert "inventory_issuance" in required_scenes()
    page = _pages()["inventory_issuance"]
    assert 'value="inventory" selected' in page
    assert "Номенклатура и склад" in page

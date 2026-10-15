"""Stage 399: MCP list projection must preserve privacy and completeness signals."""

import json
from unittest.mock import AsyncMock

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


ROWS = {
    "get_admissions": ("tools.admission", "admission", {
        "id": 1, "admission_date": "2026-10-16 12:00:00", "client_id": 2,
        "patient_id": 3, "user_id": 4, "status": "save",
        "description": "nonpersonal note", "client": {"id": 2, "cell_phone": "+7 999 123 45 67"},
        "pet": {"id": 3, "alias": "Rex", "note": "x" * 200},
    }),
    "get_invoices": ("tools.invoice", "invoice", {
        "id": 1, "invoice_date": "2026-10-16 12:00:00", "client_id": 2,
        "pet_id": 3, "doctor_id": 4, "amount": "100.00", "paid_amount": "0.00",
        "payment_status": "none", "status": "exec",
        "client": {"id": 2, "email": "person@example.test", "address": "Example street 10"},
        "invoiceDocuments": [{"description": "x" * 200}],
    }),
    "get_clients": ("tools.client", "client", {
        "id": 2, "first_name": "Anna", "last_name": "Smith", "middle_name": "M",
        "status": "ACTIVE", "cell_phone": "+7 999 123 45 67",
        "email": "person@example.test", "address": "Example street 10",
        "pets": [{"id": 3, "note": "x" * 200}],
    }),
}


def _patch_list(monkeypatch, tool, *, flat=False):
    module_name, entity, row = ROWS[tool]
    module = __import__(module_name, fromlist=["crud_list"])
    body = [row] if flat else {entity: [row], "totalCount": 1, "truncated": True}
    mocked = AsyncMock(return_value={"success": True, "data": body, "limit": 1})
    monkeypatch.setattr(module, "crud_list", mocked)
    if tool == "get_admissions":
        monkeypatch.setattr(module, "clinic_local_today", AsyncMock(return_value=None))
    return mocked


async def _call(tool, args, *, depersonalized=False):
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1, is_depersonalized=depersonalized,
    )
    with headers, runtime:
        return (await mcp.call_tool(tool, args)).structured_content


def _row(result, entity):
    data = result["data"]
    return (data if isinstance(data, list) else data[entity])[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ROWS)
@pytest.mark.parametrize("flat", [False, True])
async def test_projection_shapes_envelope_and_size(monkeypatch, tool, flat):
    mocked = _patch_list(monkeypatch, tool, flat=flat)
    entity = ROWS[tool][1]
    full = await _call(tool, {"limit": 1})
    compact = await _call(tool, {"limit": 1, "compact": True})
    selected = await _call(tool, {"limit": 1, "fields": ["id", "status"]})
    assert _row(selected, entity) == {"id": _row(full, entity)["id"],
                                      "status": _row(full, entity)["status"]}
    assert "client" not in _row(compact, entity)
    assert "pets" not in _row(compact, entity)
    assert "pet_id" in _row(compact, entity) if tool != "get_clients" else True
    assert len(json.dumps(compact).encode()) < len(json.dumps(full).encode())
    assert {k: v for k, v in compact.items() if k != "data"} == {
        k: v for k, v in full.items() if k != "data"
    }
    if not flat:
        assert compact["data"]["totalCount"] == full["data"]["totalCount"]
        assert compact["data"]["truncated"] is True
    assert all("fields" not in call.kwargs and "compact" not in call.kwargs
               for call in mocked.call_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("depersonalized", [False, True])
@pytest.mark.parametrize("mode", ["full", "fields", "compact"])
async def test_contact_matrix(monkeypatch, depersonalized, mode):
    _patch_list(monkeypatch, "get_clients")
    args = {"limit": 1}
    if mode == "fields":
        args["fields"] = ["id", "cell_phone", "email", "address", "status"]
    if mode == "compact":
        args["compact"] = True
    result = await _call("get_clients", args, depersonalized=depersonalized)
    row = _row(result, "client")
    assert row["status"] == "ACTIVE"
    if mode == "compact":
        assert not {"cell_phone", "email", "address"} & row.keys()
    elif depersonalized:
        assert row["cell_phone"] != "+7 999 123 45 67"
        assert row["email"] != "person@example.test"
        assert row["address"] != "Example street 10"
    else:
        assert row["cell_phone"] == "+7 999 123 45 67"


@pytest.mark.asyncio
async def test_conflict_diagnostic_survives_projection(monkeypatch):
    mocked = _patch_list(monkeypatch, "get_admissions")
    mocked.return_value["data"]["admission"][0]["pet_id"] = 99
    for args in ({"compact": True}, {"fields": ["id", "pet_id"]}):
        row = _row(await _call("get_admissions", args), "admission")
        assert row["pet_id"] == 99
        assert row["_mcp_identifier_conflicts"][0]["field"] == "pet_id"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_row", [
    {"id": 2, "status": {"cell_phone": "+7 999 123 45 67"}},
    ["not a record", {"cell_phone": "+7 999 123 45 67"}],
])
async def test_projection_rejects_upstream_shape_drift(monkeypatch, bad_row):
    mocked = _patch_list(monkeypatch, "get_clients")
    mocked.return_value["data"]["client"] = [bad_row]
    with pytest.raises(Exception, match="Projection"):
        await _call("get_clients", {"fields": ["id", "status"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [
    {"fields": []}, {"fields": ["client"]}, {"fields": ["owner_id"]},
    {"fields": ["id"], "compact": True},
])
async def test_invalid_projection_rejected_before_vm(monkeypatch, args):
    mocked = _patch_list(monkeypatch, "get_clients")
    with pytest.raises(Exception):
        await _call("get_clients", args)
    mocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_scope_denial_precedes_projection_validation(monkeypatch):
    mocked = _patch_list(monkeypatch, "get_clients")
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1, scopes=(),
    )
    with headers, runtime, pytest.raises(Exception) as exc:
        await mcp.call_tool("get_clients", {"fields": ["unknown_field"]})
    assert "Unknown or nested fields" not in str(exc.value)
    mocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalogue_exposes_projection():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    for name in ROWS:
        props = tools[name].inputSchema["properties"]
        assert {"fields", "compact"} <= props.keys()
        assert "local" in tools[name].description.lower()

"""Stage 411: the MCP catalog must advertise the intended reading routes."""

import pytest

from server import mcp


@pytest.fixture
async def catalog():
    return {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}


@pytest.mark.asyncio
async def test_timesheet_types_has_its_own_work_schedule_description(catalog):
    description = catalog["get_timesheet_types"].description.lower()
    assert "shift type" in description or "schedule entry type" in description
    assert "is_working_hours" in description
    assert "get_doctor_free_slots" in description
    assert description != catalog["get_timesheets"].description.lower()


@pytest.mark.asyncio
async def test_goods_name_is_absent_from_published_schema(catalog):
    goods = catalog["get_goods"].inputSchema["properties"]
    assert "name" not in goods
    assert "title" in goods


@pytest.mark.asyncio
async def test_payments_client_id_is_absent_from_published_schema(catalog):
    payments = catalog["get_payments"].inputSchema["properties"]
    assert "client_id" not in payments
    assert "status" in payments


@pytest.mark.asyncio
async def test_medical_cards_route_general_search_without_relaxing_pet_id(catalog):
    card = catalog["get_medical_cards"]
    description = card.description.lower()
    assert "get_medical_cards_by_client_id" in description
    assert "get_medical_cards_by_date" in description
    assert "general" in description or "without a known pet" in description
    assert "pet_id" in card.inputSchema["required"]


@pytest.mark.asyncio
async def test_invoices_warn_about_upstream_payment_status_drift(catalog):
    invoice = catalog["get_invoices"]
    description = invoice.description.lower()
    for word in ("payment_status", "paid_amount", "amount", "paid_amount_max", "amount_min"):
        assert word in description
    assert "out of sync" in description or "stale" in description
    assert "paginate" in description or "pagination" in description

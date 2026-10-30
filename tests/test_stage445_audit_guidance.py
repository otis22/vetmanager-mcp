"""Stage 445: discover server-side staff filters for medical-card audits."""

import pytest

from server import mcp


@pytest.mark.asyncio
async def test_audit_guidance_prefers_both_server_side_role_filters():
    catalogue = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    tool = catalogue["get_medical_cards_by_date"]
    description = tool.description
    assert "Prefer the server-side doctor_id or creator_id filter for the role named in the audit" in description
    assert "If both roles are requested, pass both IDs in the same paginated date-range call" in description
    properties = tool.inputSchema["properties"]
    assert "doctor_id" in properties and "creator_id" in properties
    assert "date_from" in properties and "date_to" in properties
    assert "limit" in properties and "offset" in properties

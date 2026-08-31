"""Stage 268 — the invoice delete tools stay removed.

They were dropped because the generic REST delete does not follow Vetmanager's
own rules for removing an invoice: an invoice that has line items is refused by
the database, and an empty one is deleted whatever state it is in, without the
rollback of related documents. A tool that destroys data on half its inputs is
not made safe by a warning in its description, so the pair is gone until the
upstream offers a delete that runs the domain rules.

This file exists so that the pair cannot come back unnoticed — through a merge,
a copy-paste from a sibling entity, or someone reading the old PRD of stage 55.
"""

import pytest
from fastmcp.exceptions import NotFoundError, ToolError

from server import mcp
from tool_access_registry import TOKEN_PRESET_CHOICES, TOOL_REQUIRED_SCOPES, tools_for_preset
from tool_descriptions import TOOL_ENTITY_MAP

REMOVED_TOOLS = ("delete_invoice", "delete_invoice_document")
# The argument each tool used to take, so that a returned tool fails this file
# on the refusal it gives — not on an argument it does not recognise.
REMOVED_TOOL_ARGUMENTS = {
    "delete_invoice": {"invoice_id": 10},
    "delete_invoice_document": {"doc_id": 20},
}


@pytest.mark.asyncio
async def test_the_removed_invoice_delete_tools_are_not_registered():
    registered = {tool.name for tool in await mcp.list_tools()}
    present = sorted(name for name in REMOVED_TOOLS if name in registered)
    assert not present, (
        f"Stage 268 removed these tools; they are registered again: {present}. "
        "Bringing them back needs an upstream delete that runs the domain rules "
        "(Bitrix task 12497), not a re-registration."
    )


@pytest.mark.parametrize("tool_name", REMOVED_TOOLS)
def test_the_removed_tools_are_absent_from_every_registry(tool_name):
    assert tool_name not in TOOL_REQUIRED_SCOPES
    assert tool_name not in TOOL_ENTITY_MAP
    for preset in TOKEN_PRESET_CHOICES:
        assert tool_name not in tools_for_preset(preset), (
            f"{tool_name} is part of preset {preset}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", REMOVED_TOOLS)
async def test_calling_a_removed_tool_reads_as_unknown_not_as_missing_rights(tool_name):
    """The refusal has to say the tool does not exist.

    A scope denial would send the caller to ask an administrator for wider
    access, and that access would never help — the tool is gone on purpose.
    """
    with pytest.raises((NotFoundError, ToolError)) as refusal:
        await mcp.call_tool(tool_name, REMOVED_TOOL_ARGUMENTS[tool_name])

    message = str(refusal.value).lower()
    assert "unknown tool" in message or "not found" in message, message
    assert "scope" not in message and "preset" not in message, message

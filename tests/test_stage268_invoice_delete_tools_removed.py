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

from server import mcp
from tool_access_registry import MARKETED_PRESET_TOOLS, TOOL_REQUIRED_SCOPES
from tool_descriptions import TOOL_ENTITY_MAP

REMOVED_TOOLS = ("delete_invoice", "delete_invoice_document")


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
    for preset, tools in MARKETED_PRESET_TOOLS.items():
        assert tool_name not in tools, f"{tool_name} is advertised by preset {preset}"

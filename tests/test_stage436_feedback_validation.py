"""Stage 436: invalid feedback calls return private, actionable errors."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ValidationError

import tools.feedback as feedback_tool


async def _client_call(mcp, arguments):
    async with Client(mcp) as client:
        return await client.call_tool("report_problem", arguments, raise_on_error=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments,field,example", [
    ({"category": "bug", "severity": "medium", "summary": "SECRET_PERSON_436"},
     "details", 'details="Safe description without personal data"'),
    ({"category": "bug", "severity": "medium", "summary": "safe", "details": "safe",
      "http_status": "SECRET_PERSON_436"}, "http_status", "http_status=422"),
    ({"category": "bug", "severity": "medium", "summary": "safe", "details": "safe",
      "params_shape": ["SECRET_PERSON_436", {"nested": "SECRET_PERSON_436"}]},
     "params_shape", 'params_shape=["date_from"]'),
])
async def test_invalid_feedback_explains_field_without_leaking_values(
    arguments, field, example, monkeypatch,
):
    from tools.feedback import FeedbackValidationMiddleware

    save = AsyncMock()
    monkeypatch.setattr(feedback_tool, "create_feedback_report", save)
    mcp = FastMCP("feedback-validation-test")
    feedback_tool.register(mcp)
    mcp.add_middleware(FeedbackValidationMiddleware())
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("fastmcp.server.server")
    logger.addHandler(handler)
    try:
        result = await _client_call(mcp, arguments)
    finally:
        logger.removeHandler(handler)
    message = result.content[0].text
    assert result.is_error is True
    assert field in message and example in message
    assert "SECRET_PERSON_436" not in message
    assert records
    assert "SECRET_PERSON_436" not in "\n".join(
        record.getMessage() + str(record.exc_info or "") for record in records
    )
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_tool_validation_and_feedback_schema_are_unchanged():
    from tools.feedback import FeedbackValidationMiddleware

    mcp = FastMCP("feedback-validation-test")
    feedback_tool.register(mcp)

    @mcp.tool
    def other_tool(count: int) -> int:
        return count

    mcp.add_middleware(FeedbackValidationMiddleware())
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    assert set(tools["report_problem"].inputSchema["required"]) == {
        "category", "severity", "summary", "details",
    }
    async with Client(mcp) as client:
        result = await client.call_tool("other_tool", {"count": "bad"}, raise_on_error=False)
    assert result.is_error is True
    assert "validation error" in result.content[0].text


@pytest.mark.asyncio
async def test_unknown_validation_shape_uses_safe_fallback():
    from tools.feedback import FeedbackValidationMiddleware

    middleware = FeedbackValidationMiddleware()

    async def raise_unexpected(_):
        raise ValidationError("SECRET_PERSON_436")

    context = SimpleNamespace(message=SimpleNamespace(name="report_problem"))
    with pytest.raises(Exception) as error:
        await middleware.on_call_tool(context, raise_unexpected)
    assert "Check report_problem inputSchema in tools/list and retry" in str(error.value)
    assert "SECRET_PERSON_436" not in str(error.value)

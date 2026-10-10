"""Stage 378: report_problem accepts one input alias and advertises canonical sources."""

import pytest

import agent_feedback_service as feedback
from exceptions import ToolInputError
from server import mcp
from storage_models import AgentFeedbackReport
from tests.runtime_factories import make_runtime_credentials


@pytest.fixture
async def feedback_store(sqlite_session_factory_builder, tmp_path, monkeypatch):
    factory = await sqlite_session_factory_builder(tmp_path / "stage378.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: factory)
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage378-test-pepper")
    return factory


def _arguments(source):
    return dict(
        credentials=make_runtime_credentials("clinic", "secret", account_id=None, bearer_token_id=None),
        category="bug", severity="medium", summary="Tool response is incomplete",
        details="A required field is absent", source=source,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["model", "human", "agent"])
async def test_source_is_stored_canonically(feedback_store, source):
    result = await feedback.create_feedback_report(**_arguments(source))
    assert result["ok"] is True
    async with feedback_store() as session:
        report = await session.get(AgentFeedbackReport, result["feedback_id"])
    assert report is not None
    assert report.source == ("model" if source == "agent" else source)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["system", "auto", "user_complaint"])
async def test_non_input_sources_are_rejected_with_canonical_choices(feedback_store, source):
    with pytest.raises(ToolInputError) as error:
        await feedback.create_feedback_report(**_arguments(source))
    message = str(error.value)
    assert "model" in message and "human" in message
    assert "agent" not in message and "auto" not in message and "user_complaint" not in message


@pytest.mark.asyncio
async def test_exported_report_problem_lists_canonical_sources():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    description = tools["report_problem"].description
    assert "source='model' for a problem detected by the agent (default)" in description
    assert "source='human' for a complaint from a person" in description
    assert "auto" not in description and "user_complaint" not in description

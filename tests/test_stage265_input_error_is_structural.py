"""Stage 265.5: an input error is recognised by its type, not by its first word.

`should_skip_report_hint` decided "this is the caller's mistake, do not offer to
file a bug report" by matching the message against prefixes like "invalid " and
"missing ". Rewording any of those six messages would silently flip the
behaviour — either pestering a user about their own typo, or swallowing a real
defect.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from agent_feedback_service import ToolInputError, should_skip_report_hint


def test_input_error_is_skipped_whatever_it_says():
    """The wording is free to change; the decision must not depend on it."""
    assert should_skip_report_hint(ToolInputError("Invalid feedback category.")) is True
    assert should_skip_report_hint(ToolInputError("Категория не подходит.")) is True
    assert should_skip_report_hint(ToolInputError("")) is True


def test_a_real_defect_still_offers_the_report():
    """A plain ToolError is a defect until proven otherwise."""
    assert should_skip_report_hint(ToolError("Vetmanager returned 500.")) is False
    # Wording that merely looks like a validation message is not enough any more.
    assert should_skip_report_hint(ToolError("Invalid response from upstream.")) is False


def test_input_error_is_still_a_tool_error():
    """Callers that catch ToolError must keep catching these."""
    assert issubclass(ToolInputError, ToolError)


@pytest.mark.parametrize(
    "call",
    [
        lambda svc: svc.sanitize_text(None, limit=10, required=True),
        lambda svc: svc.sanitize_params_shape("not-a-list"),
        lambda svc: svc.sanitize_params_shape(["not a safe name!"]),
    ],
)
def test_validation_paths_raise_the_typed_error(call):
    """The producers must raise the type, or the type protects nothing."""
    import agent_feedback_service as svc

    with pytest.raises(ToolInputError):
        call(svc)

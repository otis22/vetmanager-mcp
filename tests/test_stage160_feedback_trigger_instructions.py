"""Stage 160: strong feedback trigger instructions."""

from __future__ import annotations

import ast
from pathlib import Path

from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS


REPO_ROOT = Path(__file__).resolve().parent.parent


def _server_instructions_source() -> str:
    return (REPO_ROOT / "server.py").read_text(encoding="utf-8")


def _feedback_tool_docstring() -> str:
    source = (REPO_ROOT / "tools" / "feedback.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    for node in ast.walk(module):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "report_problem":
            docstring = ast.get_docstring(node)
            assert docstring is not None
            return docstring
    raise AssertionError("report_problem docstring not found")


def _surfaces() -> dict[str, str]:
    return {
        "server instructions": _server_instructions_source(),
        "special description": SPECIAL_TOOL_DESCRIPTIONS["report_problem"],
        "tool docstring": _feedback_tool_docstring(),
    }


def test_report_problem_successful_but_unsatisfactory_triggers_are_everywhere():
    fragments = (
        "Call report_problem",
        "even when the tool call succeeded",
        "empty result but relevant records were expected",
        "response is missing fields needed to answer",
        "tool description/docs promised or implied",
        "missing tool, parameter, filter, sort, pagination, or date semantics",
        "workaround was necessary because no direct tool or parameter exists",
        "successful response is suspicious, inconsistent, or not enough to answer",
    )
    for surface_name, text in _surfaces().items():
        for fragment in fragments:
            assert fragment in text, f"{surface_name} missing trigger fragment: {fragment!r}"


def test_report_problem_strong_privacy_suppression_is_everywhere():
    fragments = (
        "<client>",
        "<owner>",
        "<patient>",
        "<phone>",
        "<address>",
        "Do not paste raw tool response bodies",
        "raw record IDs",
        "user's verbatim message",
        "full error payloads",
        "Do not call report_problem for legitimately empty results",
    )
    for surface_name, text in _surfaces().items():
        for fragment in fragments:
            assert fragment in text, f"{surface_name} missing privacy fragment: {fragment!r}"


def test_report_problem_description_contains_category_mapping():
    description = SPECIAL_TOOL_DESCRIPTIONS["report_problem"]
    for fragment in (
        "Category mapping:",
        "missing tool/parameter/filter/sort/pagination/date semantics -> missing_tool",
        "promised or implied capability not provided -> bad_description",
        "description/docs mismatch -> bad_description",
        "contract mismatch -> contract",
        "docs/examples conflict -> docs",
    ):
        assert fragment in description


def test_readme_agent_feedback_mentions_successful_unsatisfactory_trigger():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for fragment in (
        "even when the tool call succeeded",
        "empty result but relevant records were expected",
        "response is missing fields needed to answer",
        "tool description/docs promised or implied",
        "missing tool, parameter, filter, sort, pagination, or date semantics",
        "workaround was necessary because no direct tool or parameter exists",
        "successful response is suspicious, inconsistent, or not enough to answer",
        "Do not call report_problem for legitimately empty results",
        "Do not paste raw tool response bodies",
    ):
        assert fragment in readme

"""Integration tests for MCP tools/list export contract.

Stage 16: every tool must expose meaningful description and inputSchema.
Stage 17: every list tool must expose minimum=1 and maximum=100 for limit.
"""
import asyncio
import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import mcp  # noqa: E402


def _get_all_tool_exports() -> list[dict]:
    """Return list of exported MCP tool metadata for all registered tools."""
    async def _fetch():
        tools = await mcp.list_tools()
        return [
            {
                "name": t.name,
                "description": t.to_mcp_tool().description or "",
                "schema": t.to_mcp_tool().inputSchema or {},
            }
            for t in tools
        ]
    return asyncio.run(_fetch())


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def all_tool_exports():
    return _get_all_tool_exports()


@pytest.fixture(scope="module")
def list_tools_with_limit(all_tool_exports):
    """All tools that have a 'limit' property in their inputSchema."""
    return [
        t for t in all_tool_exports
        if "limit" in t["schema"].get("properties", {})
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestToolsListSchema:
    """Stages 16-17: tools/list must export useful descriptions and schemas."""

    def test_every_tool_has_nonempty_description(self, all_tool_exports):
        missing = [t["name"] for t in all_tool_exports if not t["description"].strip()]
        assert not missing, f"Tools with empty description: {missing}"

    def test_every_tool_has_nonempty_input_schema(self, all_tool_exports):
        missing = [t["name"] for t in all_tool_exports if not t["schema"]]
        assert not missing, f"Tools with empty inputSchema: {missing}"

    def test_tool_descriptions_do_not_contain_legacy_credentials(self, all_tool_exports):
        offenders = [
            t["name"]
            for t in all_tool_exports
            if "domain:" in t["description"] or "api_key:" in t["description"]
        ]
        assert not offenders, (
            "Tools with legacy credential hints in description: "
            f"{offenders}"
        )

    def test_at_least_one_list_tool_exists(self, list_tools_with_limit):
        """Sanity check: there must be at least one tool with a limit parameter."""
        assert len(list_tools_with_limit) >= 1, (
            "No tools with 'limit' parameter found — check server registration."
        )

    def test_expected_list_tool_count(self, list_tools_with_limit):
        """There should be at least 30 list tools (Stage 17 covers 36 tools)."""
        count = len(list_tools_with_limit)
        assert count >= 30, (
            f"Expected ≥30 list tools, got {count}. "
            "Some tools may be missing LimitParam annotation."
        )

    @pytest.mark.parametrize("tool_info", _get_all_tool_exports())
    def test_limit_has_minimum_when_present(self, tool_info):
        """Every tool with a 'limit' param must declare minimum in its schema."""
        schema = tool_info["schema"]
        props = schema.get("properties", {})
        if "limit" not in props:
            pytest.skip(f"Tool '{tool_info['name']}' has no limit parameter")
        limit_schema = props["limit"]
        assert "minimum" in limit_schema, (
            f"Tool '{tool_info['name']}': limit schema missing 'minimum'. "
            f"Got: {limit_schema}"
        )

    @pytest.mark.parametrize("tool_info", _get_all_tool_exports())
    def test_limit_has_maximum_when_present(self, tool_info):
        """Every tool with a 'limit' param must declare maximum in its schema."""
        schema = tool_info["schema"]
        props = schema.get("properties", {})
        if "limit" not in props:
            pytest.skip(f"Tool '{tool_info['name']}' has no limit parameter")
        limit_schema = props["limit"]
        assert "maximum" in limit_schema, (
            f"Tool '{tool_info['name']}': limit schema missing 'maximum'. "
            f"Got: {limit_schema}"
        )

    @pytest.mark.parametrize("tool_info", _get_all_tool_exports())
    def test_limit_minimum_is_1(self, tool_info):
        """Limit minimum must be 1 (not 0 or negative)."""
        schema = tool_info["schema"]
        props = schema.get("properties", {})
        if "limit" not in props:
            pytest.skip(f"Tool '{tool_info['name']}' has no limit parameter")
        limit_schema = props["limit"]
        if "minimum" not in limit_schema:
            pytest.skip(f"Tool '{tool_info['name']}' has no minimum (covered by other test)")
        assert limit_schema["minimum"] == 1, (
            f"Tool '{tool_info['name']}': expected minimum=1, got {limit_schema['minimum']}"
        )

    @pytest.mark.parametrize("tool_info", _get_all_tool_exports())
    def test_limit_maximum_is_100(self, tool_info):
        """Limit maximum must be 100 (VETMANAGER_MAX_LIMIT)."""
        schema = tool_info["schema"]
        props = schema.get("properties", {})
        if "limit" not in props:
            pytest.skip(f"Tool '{tool_info['name']}' has no limit parameter")
        limit_schema = props["limit"]
        if "maximum" not in limit_schema:
            pytest.skip(f"Tool '{tool_info['name']}' has no maximum (covered by other test)")
        assert limit_schema["maximum"] == 100, (
            f"Tool '{tool_info['name']}': expected maximum=100, got {limit_schema['maximum']}"
        )

    @pytest.mark.parametrize("tool_info", _get_all_tool_exports())
    def test_limit_default_is_reasonable(self, tool_info):
        """Limit default must be between 1 and 100 (not 0 or 200)."""
        schema = tool_info["schema"]
        props = schema.get("properties", {})
        if "limit" not in props:
            pytest.skip(f"Tool '{tool_info['name']}' has no limit parameter")
        limit_schema = props["limit"]
        if "default" not in limit_schema:
            pytest.skip(f"Tool '{tool_info['name']}' has no default limit")
        default = limit_schema["default"]
        assert 1 <= default <= 100, (
            f"Tool '{tool_info['name']}': limit default={default} is out of range [1, 100]"
        )

    @pytest.mark.parametrize("tool_info", _get_all_tool_exports())
    def test_limit_has_description(self, tool_info):
        """Limit must have a description so LLM understands the constraint."""
        schema = tool_info["schema"]
        props = schema.get("properties", {})
        if "limit" not in props:
            pytest.skip(f"Tool '{tool_info['name']}' has no limit parameter")
        limit_schema = props["limit"]
        assert "description" in limit_schema and limit_schema["description"], (
            f"Tool '{tool_info['name']}': limit schema missing 'description'."
        )

    def test_no_tool_accepts_limit_over_100(self, list_tools_with_limit):
        """No list tool should accept limit > 100 (catches regressions)."""
        violations = [
            t["name"]
            for t in list_tools_with_limit
            if t["schema"]["properties"]["limit"].get("maximum", 0) > 100
        ]
        assert not violations, (
            f"These tools accept limit > 100: {violations}"
        )

    def test_no_tool_allows_limit_zero_or_negative(self, list_tools_with_limit):
        """No list tool should allow limit <= 0."""
        violations = [
            t["name"]
            for t in list_tools_with_limit
            if t["schema"]["properties"]["limit"].get("minimum", 0) <= 0
        ]
        assert not violations, (
            f"These tools allow limit <= 0: {violations}"
        )

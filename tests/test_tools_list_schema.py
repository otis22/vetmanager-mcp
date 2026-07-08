"""Integration tests for MCP tools/list export contract.

Stage 16: every tool must expose meaningful description and inputSchema.
Stage 17: every list tool must expose minimum=1 and maximum=100 for limit.
"""
import pytest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import mcp  # noqa: E402
from tool_access_registry import TOOL_REQUIRED_SCOPES  # noqa: E402


def _get_all_tool_exports(run_async) -> list[dict]:
    """Return list of exported MCP tool metadata for all registered tools."""
    async def _fetch():
        tools = await mcp.list_tools()
        return [
            {
                "name": t.name,
                "description": t.to_mcp_tool().description or "",
                "schema": t.to_mcp_tool().inputSchema or {},
                "meta": t.to_mcp_tool().model_dump(by_alias=True).get("_meta") or {},
            }
            for t in tools
        ]
    return run_async(_fetch())


def _tools_by_name(all_tool_exports):
    return {tool["name"]: tool for tool in all_tool_exports}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def all_tool_exports(run_async):
    return _get_all_tool_exports(run_async)


@pytest.fixture
def list_tools_with_limit(all_tool_exports):
    """All tools that have a 'limit' property in their inputSchema."""
    return [
        t for t in all_tool_exports
        if "limit" in t["schema"].get("properties", {})
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestToolsListSchema:
    """Stages 16-18: tools/list must export useful descriptions and schemas."""

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

    def test_every_tool_description_contains_domain_synonyms_hint(self, all_tool_exports):
        missing = [
            t["name"]
            for t in all_tool_exports
            if "Domain synonyms:" not in t["description"]
        ]
        assert not missing, (
            "Tools without domain synonym hints in description: "
            f"{missing}"
        )

    @pytest.mark.parametrize(
        ("tool_name", "expected_fragment"),
        [
            ("get_clients", "владелец"),
            ("get_pets", "животное"),
            ("get_admissions", "запись на приём"),
            ("get_medical_cards", "история болезни"),
            ("get_goods", "услуга"),
            ("get_good_stock_balance", "остаток на складе"),
            ("get_vaccinations", "прививка"),
            ("get_store_documents", "приходная накладная"),
            ("get_users", "ветеринар"),
        ],
    )
    def test_representative_tools_export_domain_synonyms(
        self,
        all_tool_exports,
        tool_name,
        expected_fragment,
    ):
        tool = next(t for t in all_tool_exports if t["name"] == tool_name)
        assert expected_fragment in tool["description"], (
            f"Tool '{tool_name}' description should contain '{expected_fragment}'. "
            f"Got: {tool['description']}"
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

    def test_get_payments_exports_date_filter_params(self, all_tool_exports):
        tool = next(t for t in all_tool_exports if t["name"] == "get_payments")
        properties = tool["schema"].get("properties", {})
        assert "date_from" in properties
        assert "date_to" in properties
        assert "client_id" in properties
        assert "get_client_payment_applications" in tool["description"]

    def test_get_client_payment_applications_exports_contract(self, all_tool_exports):
        tool = next(
            t for t in all_tool_exports
            if t["name"] == "get_client_payment_applications"
        )
        properties = tool["schema"].get("properties", {})
        assert "client_id" in properties
        assert "pet_id" in properties
        assert "date_from" in properties
        assert "date_to" in properties
        assert "payment applications" in tool["description"].lower()
        assert "closingOfInvoices" in tool["description"]

    def test_get_daily_schedule_exports_offset_param(self, all_tool_exports):
        tool = next(t for t in all_tool_exports if t["name"] == "get_daily_schedule")
        properties = tool["schema"].get("properties", {})
        assert "offset" in properties
        assert properties["offset"].get("default") == 0

    def test_get_medical_cards_by_date_exports_daily_control_contract(self, all_tool_exports):
        tool = next(t for t in all_tool_exports if t["name"] == "get_medical_cards_by_date")
        properties = tool["schema"].get("properties", {})
        assert "date" in properties
        assert "date_from" in properties
        assert "date_to" in properties
        assert "clinic_id" in properties
        assert "limit" in properties
        assert "offset" in properties
        assert "clinic_id" in tool["description"]
        assert "all branches" in tool["description"]

    def test_get_invoice_documents_keeps_public_invoice_id_contract(self, all_tool_exports):
        tool = next(t for t in all_tool_exports if t["name"] == "get_invoice_documents")
        properties = tool["schema"].get("properties", {})
        assert "invoice_id" in properties
        assert "document_id" not in properties
        assert "documentId" not in properties

    def test_stage185_high_impact_tools_have_safety_wording(self, all_tool_exports):
        tools = _tools_by_name(all_tool_exports)
        for tool_name in (
            "delete_client",
            "delete_pet",
            "delete_invoice",
            "delete_invoice_document",
        ):
            description = tools[tool_name]["description"]
            assert "destructive" in description.lower()
            assert "confirm" in description.lower()
            assert "exact" in description.lower()

        broadcast = tools["send_message_to_all"]["description"]
        assert "notifies every clinic user" in broadcast.lower()
        assert "send_message_to_roles" in broadcast
        assert "send_message_to_users" in broadcast
        assert "confirm" in broadcast.lower()

    def test_stage185_overlapping_tools_have_reciprocal_disambiguation(self, all_tool_exports):
        tools = _tools_by_name(all_tool_exports)
        assert "search_invoice_goods" in tools["get_goods"]["description"]
        assert "get_goods" in tools["search_invoice_goods"]["description"]

        assert "get_medical_cards_by_date" in tools["get_medical_cards"]["description"]
        assert "get_medical_cards_by_client_id" in tools["get_medical_cards"]["description"]
        assert "get_medical_cards" in tools["get_medical_cards_by_date"]["description"]
        assert "get_medical_cards" in tools["get_medical_cards_by_client_id"]["description"]

        assert "get_average_invoice" in tools["get_revenue_summary"]["description"]
        assert "get_revenue_summary" in tools["get_average_invoice"]["description"]

        assert "get_client_profile" in tools["get_clients"]["description"]
        assert "get_debtors" in tools["get_clients"]["description"]
        assert "get_inactive_clients" in tools["get_clients"]["description"]

    def test_stage185_report_ai_export_tools_explain_order_and_preconditions(self, all_tool_exports):
        tools = _tools_by_name(all_tool_exports)
        create = tools["create_report_ai_job"]["description"]
        assert "canonical order" in create.lower()
        assert "get_report_ai_job" in create

        job = tools["get_report_ai_job"]["description"]
        assert "needs_confirmation" in job
        assert "confirm_report_ai_job_candidate" in job
        assert "save_report_ai_job_as_report" in job

        data = tools["get_report_ai_job_data"]["description"]
        assert "saved" in data
        assert "existing_report_matched" in data
        assert "get_report_ai_job_export" in data

        ai_export = tools["get_report_ai_job_export"]["description"]
        assert "get_report_ai_job" in ai_export
        assert "start_report_export" in ai_export
        assert "get_report_export_file" in ai_export

        start_export = tools["start_report_export"]["description"]
        assert "known report_id" in start_export
        assert "get_report_ai_job_export" in start_export

        file_export = tools["get_report_export_file"]["description"]
        assert "start_report_export" in file_export
        assert "get_report_ai_job_export" in file_export

    def test_stage185_readme_tool_count_matches_live_tools(self, all_tool_exports):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        marker = "**"
        line = next(line for line in readme.splitlines() if "инструментов** по" in line)
        count_text = line.split(marker, 2)[1].split()[0]
        assert int(count_text) == len(all_tool_exports)

    def test_stage185_python_tool_parameters_are_schema_source(self, run_async):
        async def _fetch():
            tools = await mcp.list_tools()
            return [
                {
                    "name": tool.name,
                    "parameters": tool.parameters,
                    "input_schema": tool.to_mcp_tool().inputSchema,
                }
                for tool in tools
            ]

        exports = run_async(_fetch())
        assert len(exports) >= 100
        for tool in exports:
            assert tool["parameters"] == tool["input_schema"], tool["name"]
        helper = next(tool for tool in exports if tool["name"] == "get_report_ai_prompt_helper")
        assert helper["parameters"].get("properties") == {}

    def test_every_tool_exports_oauth_security_scheme_metadata(self, all_tool_exports):
        missing = []
        for tool in all_tool_exports:
            schemes = tool["meta"].get("securitySchemes")
            if not schemes:
                missing.append(tool["name"])
                continue
            assert schemes == [
                {
                    "type": "oauth2",
                    "scopes": list(TOOL_REQUIRED_SCOPES.get(tool["name"], ())),
                }
            ]
        assert not missing, f"Tools without OAuth securitySchemes metadata: {missing}"

    def test_limit_has_minimum_when_present(self, all_tool_exports):
        """Every tool with a 'limit' param must declare minimum in its schema."""
        checked_tools = 0
        for tool_info in all_tool_exports:
            schema = tool_info["schema"]
            props = schema.get("properties", {})
            if "limit" not in props:
                continue
            checked_tools += 1
            limit_schema = props["limit"]
            assert "minimum" in limit_schema, (
                f"Tool '{tool_info['name']}': limit schema missing 'minimum'. "
                f"Got: {limit_schema}"
            )
        assert checked_tools >= 1

    def test_limit_has_maximum_when_present(self, all_tool_exports):
        """Every tool with a 'limit' param must declare maximum in its schema."""
        checked_tools = 0
        for tool_info in all_tool_exports:
            schema = tool_info["schema"]
            props = schema.get("properties", {})
            if "limit" not in props:
                continue
            checked_tools += 1
            limit_schema = props["limit"]
            assert "maximum" in limit_schema, (
                f"Tool '{tool_info['name']}': limit schema missing 'maximum'. "
                f"Got: {limit_schema}"
            )
        assert checked_tools >= 1

    def test_limit_minimum_is_1(self, all_tool_exports):
        """Limit minimum must be 1 (not 0 or negative)."""
        checked_tools = 0
        for tool_info in all_tool_exports:
            schema = tool_info["schema"]
            props = schema.get("properties", {})
            if "limit" not in props or "minimum" not in props["limit"]:
                continue
            checked_tools += 1
            limit_schema = props["limit"]
            assert limit_schema["minimum"] == 1, (
                f"Tool '{tool_info['name']}': expected minimum=1, got {limit_schema['minimum']}"
            )
        assert checked_tools >= 1

    def test_limit_maximum_is_100(self, all_tool_exports):
        """Limit maximum must be 100 (VETMANAGER_MAX_LIMIT)."""
        checked_tools = 0
        for tool_info in all_tool_exports:
            schema = tool_info["schema"]
            props = schema.get("properties", {})
            if "limit" not in props or "maximum" not in props["limit"]:
                continue
            checked_tools += 1
            limit_schema = props["limit"]
            assert limit_schema["maximum"] == 100, (
                f"Tool '{tool_info['name']}': expected maximum=100, got {limit_schema['maximum']}"
            )
        assert checked_tools >= 1

    def test_limit_default_is_reasonable(self, all_tool_exports):
        """Limit default must be between 1 and 100 (not 0 or 200)."""
        checked_tools = 0
        for tool_info in all_tool_exports:
            schema = tool_info["schema"]
            props = schema.get("properties", {})
            if "limit" not in props or "default" not in props["limit"]:
                continue
            checked_tools += 1
            limit_schema = props["limit"]
            default = limit_schema["default"]
            assert 1 <= default <= 100, (
                f"Tool '{tool_info['name']}': limit default={default} is out of range [1, 100]"
            )
        assert checked_tools >= 1

    def test_limit_has_description(self, all_tool_exports):
        """Limit must have a description so LLM understands the constraint."""
        checked_tools = 0
        for tool_info in all_tool_exports:
            schema = tool_info["schema"]
            props = schema.get("properties", {})
            if "limit" not in props:
                continue
            checked_tools += 1
            limit_schema = props["limit"]
            assert "description" in limit_schema and limit_schema["description"], (
                f"Tool '{tool_info['name']}': limit schema missing 'description'."
            )
        assert checked_tools >= 1

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

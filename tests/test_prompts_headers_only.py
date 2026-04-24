"""Regression tests for MCP prompts under bearer-only runtime contract."""

import ast
from pathlib import Path


PROMPTS_PATH = Path(__file__).resolve().parents[1] / "prompts.py"


def _load_prompt_functions() -> tuple[str, list[ast.FunctionDef]]:
    source = PROMPTS_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)

    register_fn = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "register_prompts"
    )
    prompt_functions = [
        node
        for node in register_fn.body
        if isinstance(node, ast.FunctionDef)
    ]
    return source, prompt_functions


class TestPromptsBearerOnly:
    def test_expected_prompt_count(self):
        _, prompt_functions = _load_prompt_functions()
        assert len(prompt_functions) == 20

    def test_prompts_do_not_accept_runtime_credentials(self):
        _, prompt_functions = _load_prompt_functions()

        offenders: list[str] = []
        for fn in prompt_functions:
            arg_names = {arg.arg for arg in fn.args.args}
            if "domain" in arg_names or "api_key" in arg_names:
                offenders.append(fn.name)

        assert not offenders, (
            "These prompts still accept runtime credentials: "
            f"{offenders}"
        )

    def test_prompts_do_not_instruct_passing_credentials_to_tools(self):
        source, _ = _load_prompt_functions()

        forbidden_fragments = [
            "Use domain='",
            'Use domain="',
            "api_key='",
            'api_key="',
            "domain='{domain}'",
            "api_key='{api_key}'",
        ]
        found = [fragment for fragment in forbidden_fragments if fragment in source]
        assert not found, f"Found legacy credential hints in prompts.py: {found}"

    def test_prompts_include_bearer_runtime_instruction(self):
        source, _ = _load_prompt_functions()
        assert "Bearer token" in source
        assert "Do not ask for a clinic domain or API key" in source
        assert "do not pass them as tool arguments" in source

    def test_prompts_include_static_scope_denial_guidance(self):
        source, _ = _load_prompt_functions()
        assert "PROMPT_SCOPE_GUIDANCE" in source
        assert "If a tool is denied because of token scopes" in source
        assert "prompts are dynamically filtered" not in source

    def test_daily_revenue_prompt_does_not_call_undated_payments(self):
        source, _ = _load_prompt_functions()
        daily_revenue_section = source.split("def daily_revenue", 1)[1].split(
            "@mcp.prompt", 1
        )[0]
        assert "get_payments(limit=100" not in daily_revenue_section
        assert "get_revenue_summary" in daily_revenue_section
        assert 'mode="received"' in daily_revenue_section
        assert "truncated" in daily_revenue_section

    def test_popular_services_prompt_uses_financial_invoice_filters(self):
        source, _ = _load_prompt_functions()
        popular_services_section = source.split("def popular_services", 1)[1].split(
            "@mcp.prompt", 1
        )[0]
        assert "invoice_date_from=date_from" in popular_services_section
        assert "invoice_date_to=date_to" in popular_services_section
        assert "status='exec'" in popular_services_section
        assert "offset=offset" in popular_services_section
        assert "totalCount" in popular_services_section
        assert "paginate get_invoice_documents" in popular_services_section
        assert "get_invoices(date_from=date_from" not in popular_services_section

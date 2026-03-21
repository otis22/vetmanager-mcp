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

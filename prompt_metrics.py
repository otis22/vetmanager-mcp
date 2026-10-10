"""Bounded, best-effort observations of successful MCP prompt preparation."""

from fastmcp.server.middleware import Middleware

from service_metrics import record_prompt_request


class PromptMetricsMiddleware(Middleware):
    def __init__(self) -> None:
        self.allowed_names: frozenset[str] = frozenset()

    async def on_list_prompts(self, context, call_next):
        result = await call_next(context)
        # A prompt may occur only once per successful catalogue response.
        try:
            for name in {prompt.name for prompt in result}:
                record_prompt_request(method="list", prompt=name, allowed_names=self.allowed_names)
        except Exception:
            pass
        return result

    async def on_get_prompt(self, context, call_next):
        result = await call_next(context)
        try:
            record_prompt_request(method="get", prompt=context.message.name, allowed_names=self.allowed_names)
        except Exception:
            pass
        return result

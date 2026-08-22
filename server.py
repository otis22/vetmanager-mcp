import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn

from fastmcp import FastMCP

from agent_feedback_service import validate_feedback_runtime_config
from error_tracking import configure_error_tracking
from host_resolver import reset_billing_resolver
from observability_logging import RUNTIME_LOGGER
from rate_limit_backend import shutdown_rate_limit_backend
from storage import bootstrap_storage_schema, get_database_url, initialize_storage, shutdown_storage
from shutdown_state import begin_draining, reset_draining
from structured_logging import configure_logging
from tool_oauth_security import OAuthChallengeMiddleware, apply_tool_oauth_security_metadata
from tool_descriptions import enhance_tool_descriptions
from vetmanager_client import reset_breakers, reset_shared_http_client
from web import register_web_routes


def _log_startup_aborted(exc: Exception, *, step: str) -> None:
    RUNTIME_LOGGER.critical(
        "Startup aborted during %s: %s",
        step,
        exc,
        extra={"event_name": "startup_aborted", "step": step},
    )


def _run_startup_step(step: str, func):
    try:
        return func()
    except Exception as exc:
        _log_startup_aborted(exc, step=step)
        raise


def _load_runtime_config() -> tuple[str, str, int, str]:
    return (
        os.environ.get("MCP_TRANSPORT", "streamable-http"),
        os.environ.get("MCP_HOST", "0.0.0.0"),
        int(os.environ.get("PORT", "8000")),
        os.environ.get("MCP_PATH", "/mcp"),
    )


async def _close_step(name, operation) -> None:
    try:
        await asyncio.wait_for(operation(), timeout=5)
    except Exception:
        RUNTIME_LOGGER.warning("Graceful shutdown error", extra={"event_name": "shutdown_error", "step": name}, exc_info=True)


async def _graceful_shutdown() -> None:
    await _close_step("shutdown_storage", shutdown_storage)
    await _close_step("reset_shared_http_client", reset_shared_http_client)
    await _close_step("reset_breakers", reset_breakers)
    await _close_step("reset_billing_resolver", reset_billing_resolver)
    await _close_step("shutdown_rate_limit_backend", shutdown_rate_limit_backend)


@asynccontextmanager
async def _runtime_lifespan(_server):
    reset_draining()
    try:
        await initialize_storage()
        if get_database_url().startswith("sqlite"):
            await bootstrap_storage_schema()
        yield
    finally:
        await asyncio.wait_for(_graceful_shutdown(), timeout=15)


class _DrainingUvicornServer(uvicorn.Server):
    def handle_exit(self, sig, frame) -> None:
        begin_draining()
        RUNTIME_LOGGER.info("Shutdown drain started", extra={"event_name": "shutdown_drain_started", "signal": sig})
        super().handle_exit(sig, frame)


configure_logging()
_run_startup_step("configure_error_tracking", configure_error_tracking)

mcp = FastMCP(
    name="vetmanager",
    instructions=(
        "Vetmanager MCP Server. "
        "Credentials are provided via Authorization: Bearer <service_token> "
        "configured in your MCP client. "
        "All tools are bearer-authenticated and do not accept runtime credential arguments. "
        "Call report_problem when a tool error is unclear or even when the tool call succeeded "
        "but the result does not let you answer the user well: "
        "empty result but relevant records were expected; response is missing fields needed to answer; "
        "tool description/docs promised or implied a capability that the result does not provide; "
        "missing tool, parameter, filter, sort, pagination, or date semantics blocks a reasonable request; "
        "workaround was necessary because no direct tool or parameter exists; "
        "successful response is suspicious, inconsistent, or not enough to answer. "
        "Do not call report_problem for legitimately empty results, expected pagination endings, "
        "correct rejections of invalid user input, or normal multi-step composition. "
        "Do not paste raw tool response bodies, raw record IDs, user's verbatim message, "
        "or full error payloads. Describe the shape of the problem, not raw clinic data. "
        "Replace names, patients, phones, and addresses with <client>, <owner>, <patient>, "
        "<phone>, and <address>."
    ),
    lifespan=_runtime_lifespan,
)
mcp.add_middleware(OAuthChallengeMiddleware())

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)
register_web_routes(mcp)
enhance_tool_descriptions(mcp)
apply_tool_oauth_security_metadata(mcp)

if __name__ == "__main__":
    from secret_manager import SecretManagerError, validate_required_secrets

    try:
        _run_startup_step("validate_required_secrets", validate_required_secrets)
    except SecretManagerError as exc:
        raise SystemExit(1) from exc
    _run_startup_step(
        "validate_feedback_runtime_config",
        lambda: validate_feedback_runtime_config(database_url=get_database_url()),
    )
    transport, host, port, path = _run_startup_step(
        "transport_config",
        _load_runtime_config,
    )
    if transport not in {"http", "streamable-http", "sse"}:
        mcp.run(transport=transport, host=host, port=port, path=path)
    else:
        app = mcp.http_app(path=path, transport=transport)
        config = uvicorn.Config(app, host=host, port=port, lifespan="on", timeout_graceful_shutdown=20)
        asyncio.run(_DrainingUvicornServer(config).serve())

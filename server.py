import atexit
import asyncio
import os
import signal

from fastmcp import FastMCP

from agent_feedback_service import validate_feedback_runtime_config
from error_tracking import configure_error_tracking
from host_resolver import reset_billing_resolver
from observability_logging import RUNTIME_LOGGER
from rate_limit_backend import shutdown_rate_limit_backend
from storage import bootstrap_storage_schema, get_database_url, initialize_storage
from structured_logging import configure_logging
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


configure_logging()
_run_startup_step("configure_error_tracking", configure_error_tracking)

mcp = FastMCP(
    name="vetmanager",
    instructions=(
        "Vetmanager MCP Server. "
        "Credentials are provided via Authorization: Bearer <service_token> "
        "configured in your MCP client. "
        "All tools are bearer-authenticated and do not accept runtime credential arguments. "
        "If a tool error is unclear, use report_problem, but describe the shape of the problem, "
        "not raw clinic data. Replace names, patients, phones, and addresses with "
        "<client>, <owner>, <patient>, <phone>, and <address>."
    ),
)

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)
register_web_routes(mcp)
enhance_tool_descriptions(mcp)

async def _graceful_shutdown() -> None:
    """Stage 99.3: close shared httpx.AsyncClient keep-alive sockets with
    FIN instead of RST on SIGTERM / process exit. Also drop breaker state
    so a future in-process restart starts clean.

    Stage 107.8 (obs): structured logs via RUNTIME_LOGGER with event_name
    so operators can grep shutdown paths; the `reset_breakers` branch
    was previously silent on failure.
    """
    try:
        await reset_shared_http_client()
    except Exception:
        RUNTIME_LOGGER.warning(
            "Graceful shutdown error",
            extra={"event_name": "shutdown_error", "step": "reset_shared_http_client"},
            exc_info=True,
        )
    try:
        await reset_breakers()
    except Exception:
        RUNTIME_LOGGER.warning(
            "Graceful shutdown error",
            extra={"event_name": "shutdown_error", "step": "reset_breakers"},
            exc_info=True,
        )
    # Stage 113.F7: close billing-api resolver client + drop TTL cache.
    try:
        await reset_billing_resolver()
    except Exception:
        RUNTIME_LOGGER.warning(
            "Graceful shutdown error",
            extra={"event_name": "shutdown_error", "step": "reset_billing_resolver"},
            exc_info=True,
        )
    try:
        await shutdown_rate_limit_backend()
    except Exception:
        RUNTIME_LOGGER.warning(
            "Graceful shutdown error",
            extra={"event_name": "shutdown_error", "step": "shutdown_rate_limit_backend"},
            exc_info=True,
        )


def _install_shutdown_handlers() -> None:
    """Register SIGTERM/SIGINT handlers that drain the http pool cleanly.

    FastMCP's internal uvicorn runner already handles SIGINT — we wrap it
    only to guarantee shared-client cleanup. Uses `atexit` as a final
    backstop for unusual exit paths (test runners, embedded use).
    """

    def _run_once() -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_graceful_shutdown())
            else:
                loop.run_until_complete(_graceful_shutdown())
        except Exception:
            pass

    atexit.register(_run_once)
    # SIGTERM (docker stop) and SIGINT (Ctrl+C).
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: _run_once())
    except (ValueError, OSError):
        # Not main thread or unsupported platform — atexit is sufficient.
        pass


if __name__ == "__main__":
    from secret_manager import SecretManagerError, validate_required_secrets

    try:
        _run_startup_step("validate_required_secrets", validate_required_secrets)
    except SecretManagerError as exc:
        raise SystemExit(1) from exc
    _run_startup_step("initialize_storage", lambda: asyncio.run(initialize_storage()))
    _run_startup_step(
        "validate_feedback_runtime_config",
        lambda: validate_feedback_runtime_config(database_url=get_database_url()),
    )
    if get_database_url().startswith("sqlite"):
        _run_startup_step(
            "bootstrap_storage_schema",
            lambda: asyncio.run(bootstrap_storage_schema()),
        )
    _install_shutdown_handlers()
    transport, host, port, path = _run_startup_step(
        "transport_config",
        _load_runtime_config,
    )
    _run_startup_step(
        "mcp_run",
        lambda: mcp.run(transport=transport, host=host, port=port, path=path),
    )

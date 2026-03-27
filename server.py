import logging
import os
import asyncio

from fastmcp import FastMCP

from error_tracking import configure_error_tracking
from storage import bootstrap_storage_schema, get_database_url, initialize_storage
from structured_logging import configure_logging
from tool_descriptions import enhance_tool_descriptions
from web import register_web_routes

configure_logging()
configure_error_tracking()

mcp = FastMCP(
    name="vetmanager",
    instructions=(
        "Vetmanager MCP Server. "
        "Credentials are provided via Authorization: Bearer <service_token> "
        "configured in your MCP client. "
        "All tools are bearer-authenticated and do not accept runtime credential arguments."
    ),
)

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)
register_web_routes(mcp)
enhance_tool_descriptions(mcp)

if __name__ == "__main__":
    from secret_manager import SecretManagerError, validate_required_secrets

    try:
        validate_required_secrets()
    except SecretManagerError as exc:
        logging.critical("Startup aborted: %s", exc)
        raise SystemExit(1) from exc
    asyncio.run(initialize_storage())
    if get_database_url().startswith("sqlite"):
        asyncio.run(bootstrap_storage_schema())
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    path = os.environ.get("MCP_PATH", "/mcp")
    mcp.run(transport=transport, host=host, port=port, path=path)

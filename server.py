import logging
import os

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse

from landing_page import render_landing_page
from tool_descriptions import enhance_tool_descriptions

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

mcp = FastMCP(
    name="vetmanager",
    instructions=(
        "Vetmanager MCP Server. "
        "Credentials are provided via Authorization: Bearer <service_token> "
        "configured in your MCP client. "
        "All tools are bearer-authenticated and do not accept runtime credential arguments."
    ),
)


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def landing_page(request: Request) -> HTMLResponse:
    """Render the public product landing page."""
    return HTMLResponse(render_landing_page())

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)
enhance_tool_descriptions(mcp)

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    path = os.environ.get("MCP_PATH", "/mcp")
    mcp.run(transport=transport, host=host, port=port, path=path)

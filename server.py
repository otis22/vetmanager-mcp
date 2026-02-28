import logging
import os

from fastmcp import FastMCP

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)

mcp = FastMCP(
    name="vetmanager",
    instructions=(
        "Vetmanager MCP Server. "
        "Credentials are provided via X-VM-Domain and X-VM-Api-Key HTTP headers "
        "configured in your mcp.json (Variant A). "
        "All tools are headers-only and do not accept runtime credential arguments. "
        "X-VM-Domain — clinic subdomain (e.g. 'myclinic'); "
        "X-VM-Api-Key — REST API key from Vetmanager Settings → Integration → Rest API."
    ),
)

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    path = os.environ.get("MCP_PATH", "/mcp")
    mcp.run(transport=transport, host=host, port=port, path=path)

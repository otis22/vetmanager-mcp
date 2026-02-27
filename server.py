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
        "Vetmanager MCP Server. Each tool requires 'domain' and 'api_key' parameters "
        "so the server can connect to the correct clinic instance. "
        "domain — subdomain of the clinic (e.g. 'myclinic'), "
        "api_key — REST API key from Vetmanager Settings → Integration → Rest API."
    ),
)

from tools import register_all  # noqa: E402
from prompts import register_prompts  # noqa: E402

register_all(mcp)
register_prompts(mcp)

if __name__ == "__main__":
    mcp.run()

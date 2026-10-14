"""Test-only MCP slot that pauses cache finalization after an upstream write."""

import asyncio
import os
from pathlib import Path

import cache_write_barrier
from server import _run_http_server


hook = Path(os.environ["STAGE385_PG_HOOK_DIR"])
finish = cache_write_barrier.finish_write


async def pause_before_finish(tag: str) -> None:
    if os.environ.get("STAGE385_PG_HOOK_SLOT") == "writer" and (hook / "armed").exists():
        (hook / "entered").write_text("upstream write returned")
        for _ in range(600):
            if (hook / "release").exists():
                break
            await asyncio.sleep(.05)
        else:
            raise TimeoutError("PG outage probe was not released")
    await finish(tag)


cache_write_barrier.finish_write = pause_before_finish
_run_http_server(transport="streamable-http", host="127.0.0.1",
                 port=int(os.environ["PORT"]), path="/mcp")

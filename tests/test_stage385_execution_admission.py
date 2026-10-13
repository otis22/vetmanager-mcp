"""An HTTP disconnect must not hide a tool still executing in its session task."""

import asyncio

import pytest

from shutdown_state import admit_write, begin_draining, finish_write, in_flight_writes, reset_draining, wait_for_writes
from write_admission import ExecutionAdmissionMiddleware


@pytest.mark.asyncio
async def test_detached_tool_keeps_drain_open_until_execution_finishes():
    reset_draining()
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocked_tool(_context):
        started.set()
        await release.wait()

    assert admit_write()  # HTTP request lifetime.
    task = asyncio.create_task(ExecutionAdmissionMiddleware().on_call_tool(object(), blocked_tool))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        finish_write()  # The transport response ends after client disconnect.
        begin_draining()
        assert in_flight_writes() == 1
        assert not wait_for_writes(0)
        release.set()
        await asyncio.wait_for(task, timeout=1)
        assert in_flight_writes() == 0
    finally:
        release.set()
        if not task.done():
            await task
        reset_draining()

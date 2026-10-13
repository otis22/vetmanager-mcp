"""SSE close is allowed only after the write fence and zero in-flight writes."""

from server import _close_sse_for_rollout
from shutdown_state import admit_write, begin_draining, finish_write, reset_draining


class _Transport:
    def __init__(self):
        self.closed = 0

    def close_standalone_sse_stream(self):
        self.closed += 1


def test_sse_close_waits_for_write_fence_and_zero_in_flight(monkeypatch):
    monkeypatch.setenv("STREAMABLE_HTTP_DRAIN_ENABLED", "true")
    transport = _Transport()
    manager = type("Manager", (), {"_server_instances": {"session": transport}})()
    reset_draining()
    try:
        assert _close_sse_for_rollout(manager) is False
        assert admit_write()
        begin_draining()
        assert _close_sse_for_rollout(manager) is False
        finish_write()
        assert _close_sse_for_rollout(manager) is True
        assert transport.closed == 1
    finally:
        reset_draining()

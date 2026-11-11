"""Stage 453: a bounded per-account trace for MCP handshake attempts."""

import asyncio
import json
import logging

import fakeredis
import pytest

import mcp_transport_observation as observation
import service_metrics
from request_context import RequestContextHeaderMiddleware
from shared_metric_counters import COUNTERS_KEY, RedisMetricCounters, wait_pending


TOKEN = "vm_st_" + "x" * 43  # synthetic, never a credential
INIT = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}).encode()
LIST = b'{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'


@pytest.fixture(autouse=True)
def _enable_runtime_log_after_migration_tests(monkeypatch):
    # Alembic fileConfig in an earlier suite test may disable this logger.
    monkeypatch.setattr(observation.RUNTIME_LOGGER.logger, "disabled", False)


async def _exchange(body, *, status=200, headers=(), chunks=None, response=None, read=False):
    seen = []
    request_parts = chunks or [body]
    queue = [{"type": "http.request", "body": part, "more_body": i < len(request_parts)-1}
             for i, part in enumerate(request_parts)]

    async def receive():
        if queue:
            return queue.pop(0)
        return {"type": "http.disconnect"}

    async def app(_scope, recv, send):
        if read:
            while True:
                part = await recv()
                seen.append((part["body"], part.get("more_body", False)))
                if not part.get("more_body", False):
                    break
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": response or b'{}'})

    sent = []
    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/mcp", "method": "POST", "headers": headers}
    await RequestContextHeaderMiddleware(observation.MCPTransportObservationMiddleware(app))(
        scope, receive, send)
    await observation.wait_handshake_observations()
    return sent, seen


def _events(caplog):
    return [r for r in caplog.records if getattr(r, "event_name", None) == "mcp_handshake"]


@pytest.mark.asyncio
async def test_early_rejection_still_names_method_account_and_request_id(monkeypatch, caplog):
    async def lookup(_token, _source):
        return 73
    monkeypatch.setattr(observation, "_lookup_handshake_account", lookup)
    body = INIT
    headers = [(b"authorization", b"Bearer " + TOKEN.encode()),
               (b"x-request-id", b"request_453")]
    with caplog.at_level(logging.INFO):
        sent, seen = await _exchange(body, status=400, headers=headers,
                                     chunks=[body[:17], body[17:]], read=True,
                                     response=b'{"error":"Bad Request: Missing session ID"}')
    record = _events(caplog)[0]
    assert seen == [(body[:17], True), (body[17:], False)]
    assert (record.rpc_method, record.http_method, record.channel) == ("initialize", "POST", "mcp_http")
    assert (record.account_id, record.auth_source, record.auth_outcome) == (73, "service_bearer", "matched")
    assert (record.protocol_version, record.http_status, record.reason) == ("2025-03-26", 400, "missing_session")
    assert record.request_id == dict(sent[0]["headers"])[b"x-request-id"].decode()
    assert record.observed_at.endswith("Z")
    assert TOKEN not in str(record.__dict__)


@pytest.mark.asyncio
async def test_early_406_without_downstream_receive_is_observed(monkeypatch, caplog):
    monkeypatch.setattr(observation, "_lookup_handshake_account", lambda *_: asyncio.sleep(0, result=73))
    with caplog.at_level(logging.INFO):
        sent, _ = await _exchange(LIST, status=406, headers=[(b"authorization", b"Bearer " + TOKEN.encode()),
            (b"mcp-protocol-version", b"2025-03-26")],
            response=b'{"error":"Not Acceptable: Client must accept both application/json and text/event-stream"}')
    record = _events(caplog)[0]
    assert sent[0]["status"] == 406
    assert (record.rpc_method, record.protocol_version, record.reason) == ("tools/list", "2025-03-26", "invalid_accept")
    assert record.account_id == 73


@pytest.mark.asyncio
async def test_unknown_large_body_is_bounded_and_does_not_copy_text(monkeypatch, caplog):
    monkeypatch.setattr(observation, "_lookup_handshake_account", lambda *_: asyncio.sleep(0, result=None))
    payload = b'NOT_FOR_LOG' * 7000
    with caplog.at_level(logging.INFO):
        await _exchange(payload, status=400, chunks=[payload[:1024], payload[1024:]])
    record = _events(caplog)[0]
    assert (record.rpc_method, record.reason, record.account_id) == ("unknown", "body_too_large", None)
    assert b"NOT_FOR_LOG" not in str(record.__dict__).encode()


@pytest.mark.asyncio
async def test_rpc_error_and_shared_counter_have_only_bounded_labels(monkeypatch, caplog):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(redis_client)
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setattr(observation, "_lookup_handshake_account", lambda *_: asyncio.sleep(0, result=None))
    with caplog.at_level(logging.INFO):
        await _exchange(INIT, response=b'{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"private"}}',
                        headers=[(b"authorization", b"Bearer " + TOKEN.encode())])
        await _exchange(LIST, response=b'event: message\ndata: {"jsonrpc":"2.0","id":2,"error":{"code":-32600,"message":"private"}}\n\n',
                        headers=[(b"authorization", b"Bearer " + TOKEN.encode())])
    assert [r.reason for r in _events(caplog)] == ["rpc_error", "rpc_error"]
    assert await wait_pending()
    assert backend.snapshot()["mcp_handshake_total"]["initialize|service_bearer|unmatched|rpc_error"] == 1
    assert backend.snapshot()["mcp_handshake_total"]["tools/list|service_bearer|unmatched|rpc_error"] == 1
    assert "private" not in service_metrics.render_prometheus_metrics()
    assert not any("mcp_handshake_total" in field for field in redis_client.hgetall(COUNTERS_KEY))


@pytest.mark.asyncio
async def test_saturated_lookup_is_skipped_and_response_keeps_running(monkeypatch, caplog):
    class BusySlots:
        def acquire(self, *, blocking):
            assert blocking is False
            return False

    async def forbidden_lookup(*_args):
        raise AssertionError("saturated lookup reached the DB")

    monkeypatch.setattr(observation, "_HANDSHAKE_SLOTS", BusySlots())
    monkeypatch.setattr(observation, "_lookup_handshake_account", forbidden_lookup)
    with caplog.at_level(logging.INFO):
        sent, _ = await _exchange(INIT, headers=[(b"authorization", b"Bearer " + TOKEN.encode())])
    assert sent[0]["status"] == 200
    event = _events(caplog)[0]
    assert event.auth_outcome == "lookup_failed" and event.account_id is None


@pytest.mark.asyncio
async def test_many_small_chunks_keep_exact_downstream_stream(caplog):
    chunks = [b"a"] * 129
    with caplog.at_level(logging.INFO):
        _, seen = await _exchange(b"", chunks=chunks, read=True, status=400)
    assert seen == [(b"a", True)] * 128 + [(b"a", False)]
    event = _events(caplog)[0]
    assert (event.rpc_method, event.reason) == ("unknown", "body_not_read")


def test_waiter_ignores_tasks_from_an_earlier_event_loop():
    foreign_loop = asyncio.new_event_loop()
    foreign_task = foreign_loop.create_task(asyncio.sleep(10))
    observation._HANDSHAKE_TASKS.add(foreign_task)
    try:
        asyncio.run(observation.wait_handshake_observations())
    finally:
        observation._HANDSHAKE_TASKS.discard(foreign_task)
        foreign_task.cancel()
        try:
            foreign_loop.run_until_complete(foreign_task)
        except asyncio.CancelledError:
            pass
        foreign_loop.close()


@pytest.mark.asyncio
async def test_empty_post_is_not_claimed_as_a_handshake(monkeypatch, caplog):
    async def forbidden_lookup(*_args):
        raise AssertionError("empty POST must not trigger an account lookup")

    monkeypatch.setattr(observation, "_lookup_handshake_account", forbidden_lookup)
    with caplog.at_level(logging.INFO):
        await _exchange(b"", status=400,
                        headers=[(b"authorization", b"Bearer " + TOKEN.encode())])
    assert _events(caplog) == []

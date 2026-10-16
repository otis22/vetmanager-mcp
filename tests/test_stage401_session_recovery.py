"""Stage 401: actionable session error and aggregate repeat signal."""

import json

import fakeredis
import pytest

from mcp_transport_observation import MCPTransportObservationMiddleware
from shared_metric_counters import RedisMetricCounters, wait_pending
import service_metrics
import shared_metric_counters


ERROR = {"jsonrpc": "2.0", "id": "server-error", "error": {
    "code": -32600, "message": "Session not found"}}


async def request(*, client="test-bearer-1", status=404, payload=None,
                  headers=(), chunks=1, raw_body=None):
    body = raw_body if raw_body is not None else json.dumps(payload or ERROR).encode()

    async def inner(_scope, _receive, send):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-length", str(len(body)).encode()), *headers]})
        size = len(body) // chunks
        for index in range(chunks):
            part = body[index * size:] if index == chunks - 1 else body[index * size:(index + 1) * size]
            await send({"type": "http.response.body", "body": part,
                        "more_body": index < chunks - 1})

    sent = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        sent.append(message)
    await MCPTransportObservationMiddleware(inner)(
        {"type": "http", "path": "/mcp", "method": "POST",
         "client": ("198.51.100.1", 5000), "headers": [(b"mcp-session-id", b"secret-id"),
                                                   (b"authorization", f"Bearer {client}".encode())]},
        receive, send)
    return sent


@pytest.mark.asyncio
async def test_guidance_preserves_transport_and_jsonrpc_contract(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage401-test-secret")
    sent = await request(chunks=2)
    body = b"".join(message["body"] for message in sent[1:])
    result = json.loads(body)
    assert sent[0]["status"] == 404
    assert result["jsonrpc"] == ERROR["jsonrpc"]
    assert result["id"] == ERROR["id"]
    assert result["error"]["code"] == ERROR["error"]["code"]
    assert "initialize" in result["error"]["message"]
    assert "Mcp-Session-Id" in result["error"]["message"]
    assert "secret-id" not in body.decode()
    assert dict(sent[0]["headers"])[b"content-length"] == str(len(body)).encode()
    assert await wait_pending()
    assert backend.snapshot()["mcp_transport_rejections_total"]["404|session_not_found"] == 1


@pytest.mark.asyncio
async def test_repeated_client_is_aggregate_only_and_marker_has_ttl(monkeypatch):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(redis_client)
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage401-test-secret")
    for client in ("test-bearer-1", "test-bearer-2", "test-bearer-1"):
        await request(client=client)
    assert await wait_pending()
    snapshot = backend.snapshot()
    assert snapshot["mcp_session_retries_total"] == 1
    assert snapshot["mcp_transport_rejections_total"]["404|session_not_found"] == 3
    keys = list(redis_client.scan_iter())
    assert len([key for key in keys if "session-retry:" in key]) == 2
    assert all(redis_client.ttl(key) > 0 for key in keys if "session-retry:" in key)
    rendered = service_metrics.render_prometheus_metrics()
    assert "vetmanager_mcp_session_retries_total 1" in rendered
    assert "test-bearer" not in rendered
    assert "secret-id" not in rendered
    assert not any("test-bearer" in key or "secret-id" in key for key in keys)


@pytest.mark.asyncio
async def test_other_responses_and_encoded_error_pass_through(monkeypatch):
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage401-test-secret")
    for status, payload, headers in (
        (400, {"error": "Bad Request: Missing session ID"}, ()),
        (404, {"error": {"code": -32600, "message": "Another error"}}, ()),
        (404, ERROR, ((b"content-encoding", b"gzip"),)),
    ):
        sent = await request(status=status, payload=payload, headers=headers)
        assert json.loads(b"".join(message["body"] for message in sent[1:])) == payload

    for original in (b"not json", json.dumps({**ERROR, "padding": "x" * 5000}).encode()):
        sent = await request(raw_body=original, chunks=2)
        assert b"".join(message["body"] for message in sent[1:]) == original


@pytest.mark.asyncio
async def test_fixed_slot_collision_undercounts_without_false_repeat(monkeypatch):
    assert shared_metric_counters.MCP_SESSION_RETRY_SLOTS <= 4096
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(redis_client)
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setattr(shared_metric_counters, "MCP_SESSION_RETRY_SLOTS", 1)
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage401-test-secret")
    await request(client="first")
    await request(client="second")
    assert await wait_pending()
    assert backend.snapshot()["mcp_session_retries_total"] == 0
    await request(client="first")
    assert await wait_pending()
    assert backend.snapshot()["mcp_session_retries_total"] == 1
    keys = list(redis_client.scan_iter(match="vetmanager:metrics:v1:session-retry:*"))
    assert len(keys) == 1
    redis_client.delete(keys[0])  # expired marker starts a new observation window
    await request(client="first")
    assert await wait_pending()
    assert backend.snapshot()["mcp_session_retries_total"] == 1


@pytest.mark.asyncio
async def test_metric_failure_does_not_change_recovery_response(monkeypatch):
    class BrokenBackend:
        def record_session_retry(self, _digest):
            raise RuntimeError("redis unavailable")

        def increment(self, *_args):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", BrokenBackend)
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage401-test-secret")
    sent = await request()
    assert sent[0]["status"] == 404
    assert "initialize" in json.loads(sent[1]["body"])["error"]["message"]
    assert await wait_pending()

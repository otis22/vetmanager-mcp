"""Stage 386: transport failures are counted without exposing request data."""

import asyncio

import fakeredis
import pytest

from mcp_transport_observation import MCPTransportObservationMiddleware
from shared_metric_counters import COUNTERS_KEY, RedisMetricCounters, wait_pending
import service_metrics


async def _request(app, *, status, body, headers=(), path="/mcp", observed_path="/mcp"):
    async def inner(_scope, _receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": body})

    sent = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        sent.append(message)
    await app(inner, path=observed_path)({"type": "http", "path": path, "method": "POST",
                      "headers": headers}, receive, send)
    assert sent[0]["status"] == status
    assert sent[1]["body"] == body


@pytest.mark.asyncio
async def test_transport_reasons_are_bounded_and_shared(monkeypatch):
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(redis_client)
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
    session = b'{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Session not found"}}'
    await _request(MCPTransportObservationMiddleware, status=404, body=session,
                   headers=[(b"mcp-session-id", b"secret-session-id")])
    await _request(MCPTransportObservationMiddleware, status=400,
                   body=b'{"error":"missing_authorization"}')
    await _request(MCPTransportObservationMiddleware, status=400,
                   body=b'{"error":"Bad Request: Missing session ID"}')
    await _request(MCPTransportObservationMiddleware, status=400,
                   body=b'{"error":{"message":"Bad Request: Unsupported protocol version: missing_authorization"}}')
    await _request(MCPTransportObservationMiddleware, status=400,
                   body=b'{"error":{"message":"Bad Request: Unsupported protocol version: Missing session ID"}}')
    await _request(MCPTransportObservationMiddleware, status=406,
                   body=b'{"error":"Not Acceptable: Client must accept both application/json and text/event-stream"}')
    await _request(MCPTransportObservationMiddleware, status=404,
                   body=b'{"error":"other"}')
    await _request(MCPTransportObservationMiddleware, status=200, body=b"ok")
    await _request(MCPTransportObservationMiddleware, status=200, body=b"ok",
                   path="/custom-mcp", observed_path="/custom-mcp")
    await _request(MCPTransportObservationMiddleware, status=404, body=session,
                   path="/healthz")
    assert await wait_pending()
    metrics = backend.snapshot()["mcp_transport_rejections_total"]
    assert metrics == {"404|session_not_found": 1, "400|missing_auth": 1,
                       "400|missing_session": 1, "400|other": 2,
                       "406|invalid_accept": 1, "404|other": 1}
    requests = backend.snapshot()["http_requests_total"]
    assert requests == {"/mcp|POST|404": 2, "/mcp|POST|400": 4,
                        "/mcp|POST|406": 1, "/mcp|POST|200": 1,
                        "/custom-mcp|POST|200": 1}
    rendered = service_metrics.render_prometheus_metrics()
    assert "# TYPE vetmanager_mcp_transport_rejections_total counter" in rendered
    assert 'vetmanager_mcp_transport_rejections_total{status_code="404",reason="session_not_found"} 1' in rendered
    assert "secret-session-id" not in rendered
    assert not any("mcp_transport_rejections_total" in field
                   for field in redis_client.hgetall(COUNTERS_KEY))


@pytest.mark.asyncio
async def test_open_sse_forwards_first_chunk_before_stream_finishes():
    release = asyncio.Event()
    first_chunk = asyncio.Event()
    sent = []

    async def stream(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")]})
        await send({"type": "http.response.body", "body": b": ping\n\n",
                    "more_body": True})
        await release.wait()
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("more_body"):
            first_chunk.set()

    task = asyncio.create_task(MCPTransportObservationMiddleware(stream)(
        {"type": "http", "path": "/mcp", "method": "GET", "headers": []},
        receive, send))
    try:
        await asyncio.wait_for(first_chunk.wait(), timeout=1)
        assert not task.done()
        assert sent[0]["headers"] == [(b"content-type", b"text/event-stream")]
        assert sent[1]["body"] == b": ping\n\n"
    finally:
        release.set()
        done, _pending = await asyncio.wait({task}, timeout=1)
        if not done:
            task.cancel()
            await asyncio.wait({task}, timeout=1)
            raise AssertionError("SSE test task did not finish")
        await task

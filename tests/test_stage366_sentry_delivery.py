"""Stage 366: Sentry transport failures stay observable without exposing events."""

import errno
import logging
import socket
import time
import warnings
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import sentry_sdk
from fastmcp.exceptions import ToolError
from sentry_sdk.envelope import Envelope, Item

import error_tracking
from service_metrics import reset_service_metrics, snapshot_service_metrics, render_prometheus_metrics
from tool_error_tracking import ToolErrorTrackingMiddleware


@pytest.fixture
def transport():
    reset_service_metrics()
    with warnings.catch_warnings():
        # SDK 2.x has no supported reset API; its guard restores the prior
        # client, but warns about the context-manager form under strict CI.
        warnings.filterwarnings("ignore", message="Using the return value of sentry_sdk.init as a context manager", category=DeprecationWarning)
        with sentry_sdk.init(
            dsn="http://public@127.0.0.1:1/1",
            transport=error_tracking.ObservableSentryTransport,
            default_integrations=False,
            auto_enabling_integrations=False,
            send_client_reports=False,
        ):
            yield sentry_sdk.get_client().transport


def _envelope(*types):
    return Envelope(items=[Item("{\"message\":\"private event\"}", type=kind) for kind in types])


@pytest.mark.asyncio
async def test_network_failure_is_async_counted_and_does_not_change_tool_reply(transport, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(error_tracking, "_configured", True)
    failure = ToolError("upstream failed")

    async def fail(_context):
        raise failure

    with patch.object(
        transport._pool, "request",
        side_effect=OSError(errno.ENETUNREACH, "private event https://secret.invalid/export/locator"),
    ):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="sentry_sdk.push_scope is deprecated", category=DeprecationWarning)
            started = time.monotonic()
            with pytest.raises(ToolError) as raised:
                await ToolErrorTrackingMiddleware().on_call_tool(
                    SimpleNamespace(message=SimpleNamespace(name="get_clients")), fail
                )
            elapsed = time.monotonic() - started
            transport.flush(timeout=3)

    assert raised.value is failure
    assert elapsed < 0.5
    losses = snapshot_service_metrics()["sentry_delivery_lost_total"]
    assert losses["route"] >= 1
    assert 'vetmanager_sentry_delivery_lost_total{reason="route"}' in render_prometheus_metrics()
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "sentry_delivery_lost" in messages
    assert "private event" not in messages
    assert "secret.invalid" not in messages
    assert "/export/locator" not in messages


def test_intentional_sanitizer_drop_is_not_delivery_loss(transport):
    transport.record_lost_event("before_send", data_category="error")
    assert snapshot_service_metrics()["sentry_delivery_lost_total"] == {}


def test_success_counts_only_error_items_and_resets_prior_reason(transport):
    with patch.object(transport._pool, "request", side_effect=OSError(errno.ENETUNREACH, "private")):
        transport._send_envelope(_envelope("event"))
    response = SimpleNamespace(status=200, headers={}, close=lambda: None)
    with patch.object(transport._pool, "request", return_value=response):
        transport._send_envelope(_envelope("client_report"))
        transport._send_envelope(_envelope("event", "client_report"))
    snapshot = snapshot_service_metrics()
    assert snapshot["sentry_delivery_lost_total"]["route"] == 1
    assert snapshot["sentry_delivery_accepted_total"] == 1


def test_initial_http_429_is_counted_once(transport):
    response = SimpleNamespace(status=429, headers={}, close=lambda: None)
    with patch.object(transport._pool, "request", return_value=response):
        transport._send_envelope(_envelope("event"))
    assert snapshot_service_metrics()["sentry_delivery_lost_total"]["rate_limited"] == 1


def test_sequential_dns_http_failure_and_success_do_not_share_reason(transport, caplog):
    caplog.set_level(logging.DEBUG)
    with patch.object(transport._pool, "request", side_effect=socket.gaierror("secret.example")):
        transport._send_envelope(_envelope("event"))
    failed = SimpleNamespace(status=500, headers={}, data=b"private response secret", close=lambda: None)
    with patch.object(transport._pool, "request", return_value=failed):
        transport._send_envelope(_envelope("event"))
    accepted = SimpleNamespace(status=200, headers={}, close=lambda: None)
    with patch.object(transport._pool, "request", return_value=accepted):
        transport._send_envelope(_envelope("event"))
    snapshot = snapshot_service_metrics()
    assert snapshot["sentry_delivery_lost_total"] == {"dns": 1, "http_error": 1}
    assert snapshot["sentry_delivery_accepted_total"] == 1
    logs = "\n".join(record.getMessage() for record in caplog.records)
    assert "secret.example" not in logs
    assert "private response secret" not in logs
    assert "private event" not in logs


def test_urllib3_retry_record_is_sanitized_only_during_sentry_request(transport, caplog):
    pool_logger = logging.getLogger("urllib3.connectionpool")
    connection_logger = logging.getLogger("urllib3.connection")
    caplog.set_level(logging.WARNING, logger="urllib3.connectionpool")
    caplog.set_level(logging.WARNING, logger="urllib3.connection")

    def fail(*_args, **_kwargs):
        pool_logger.warning("Retrying secret.example/export/locator")
        connection_logger.warning("TLS failure secret.example/export/locator")
        raise OSError(errno.ENETUNREACH, "private")

    with patch.object(transport._pool, "request", side_effect=fail):
        transport._send_envelope(_envelope("event"))
    connection_logger.warning("ordinary diagnostic")
    messages = [record.getMessage() for record in caplog.records if record.name.startswith("urllib3.")]
    assert messages == [
        "sentry_transport_diagnostic_suppressed",
        "sentry_transport_diagnostic_suppressed",
        "ordinary diagnostic",
    ]


def test_internal_sdk_request_failure_is_distinct_from_network_failure(transport):
    with patch.object(transport._pool, "request", side_effect=RuntimeError("private request state")):
        transport._send_envelope(_envelope("event"))
    assert snapshot_service_metrics()["sentry_delivery_lost_total"] == {"sdk_error": 1}


def test_queue_overflow_on_caller_thread_is_counted_without_changing_capture(transport):
    with patch.object(transport._worker, "submit", return_value=False):
        transport.capture_envelope(_envelope("event"))
    assert snapshot_service_metrics()["sentry_delivery_lost_total"] == {"queue_overflow": 1}


@pytest.mark.parametrize(
    ("socket_failure", "reason"),
    [
        (socket.gaierror("fixture DNS failure"), "dns"),
        (OSError(errno.ENETUNREACH, "fixture route failure"), "route"),
        (socket.timeout("fixture connect timeout"), "timeout"),
    ],
)
def test_urllib3_wrapped_network_failure_keeps_root_cause(transport, socket_failure, reason):
    # Let urllib3 build its own NameResolutionError/NewConnectionError and
    # MaxRetryError wrappers; mocking _pool.request would skip the risky path.
    with patch("urllib3.connection.connection.create_connection", side_effect=socket_failure):
        transport._send_envelope(_envelope("event"))
    assert snapshot_service_metrics()["sentry_delivery_lost_total"] == {reason: 1}

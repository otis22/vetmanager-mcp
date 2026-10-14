"""One activation scanner and one bounded gauge snapshot across MCP slots."""

import fakeredis

import service_metrics
import shared_metric_counters
from shared_metric_counters import RedisMetricCounters


def test_activation_scan_lease_and_owner_handoff():
    server = fakeredis.FakeServer()
    slots = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
             for _ in range(3)]
    assert slots[0].claim_activation_scan("owner-a")
    assert not slots[1].claim_activation_scan("owner-b")
    assert not slots[2].release_activation_scan("owner-b")
    assert slots[0].release_activation_scan("owner-a")
    assert slots[1].claim_activation_scan("owner-b")


def test_activation_snapshot_and_alert_claim_are_shared(monkeypatch):
    server = fakeredis.FakeServer()
    slots = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
             for _ in range(2)]
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: slots[1])
    slots[0].publish_activation_snapshot({
        "account_last_request_age_avg_hours": 25.0,
        "account_last_request_age_p95_hours": 30.0,
        "activation_funnel_accounts": {"token_issued": 2},
        "activation_event_accounts": {}, "first_session_gauges": {},
    })
    assert slots[1].activation_snapshot()["account_last_request_age_avg_hours"] == 25.0
    assert slots[0].claim_activation_alert("a" * 64, 24)
    assert not slots[1].claim_activation_alert("a" * 64, 24)
    slots[1].clear_activation_alerts("a" * 64)
    assert slots[0].claim_activation_alert("a" * 64, 24)


def test_account_age_export_uses_aggregate_without_account_id(monkeypatch):
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: None)
    service_metrics.set_account_last_request_age_hours({1: 10.0, 2: 30.0})
    rendered = service_metrics.render_prometheus_metrics()
    assert 'vetmanager_account_last_request_age_avg_hours 20.0' in rendered
    assert 'vetmanager_account_last_request_age_p95_hours 29.0' in rendered
    assert 'vetmanager_account_last_request_age_hours{account_id=' not in rendered

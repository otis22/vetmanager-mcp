"""Stage 464: every slot observed, independent readiness, bounded incidents."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys
import yaml

from scripts.stage464_downtime import Sample, classify_incidents, load_snapshot
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_all_slots_have_up_and_probe_without_tripling_application_counters() -> None:
    config = yaml.safe_load((ROOT / "ops/prometheus/prometheus.yml").read_text())
    jobs = {job["job_name"]: job for job in config["scrape_configs"]}
    assert jobs["vetmanager-mcp"]["static_configs"][0]["targets"] == ["mcp:8000"]
    workers = jobs["vetmanager-workers"]
    assert [(item["targets"], item["labels"]["slot"]) for item in workers["static_configs"]] == [
        (["mcp:8000"], "mcp"), (["mcp2:8000"], "mcp2"), (["mcp3:8000"], "mcp3")]
    assert workers["metric_relabel_configs"] == [{"source_labels": ["__name__"], "regex": ".*", "action": "drop"}]
    assert jobs["vetmanager-availability"]["static_configs"][0]["targets"] == ["availability-probe:8003"]
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    probe = compose["services"]["availability-probe"]
    assert "production" in probe["profiles"] and not probe.get("ports")
    assert "METRICS_AUTH_TOKEN" in probe["environment"]
    assert "SITE_BASE_URL" in probe["environment"]
    assert probe["healthcheck"]["retries"] == 3
    assert compose["services"]["prometheus"]["depends_on"]["availability-probe"]["condition"] == "service_healthy"


def test_dashboard_distinguishes_health_from_readiness_and_missing_data() -> None:
    panels = {panel["title"]: panel for panel in json.loads(
        (ROOT / "ops/grafana/dashboards/vetmanager-overview.json").read_text())["panels"]}
    assert "up{job=\"vetmanager-workers\"}" in panels["Worker metrics scrape up"]["targets"][0]["expr"]
    ready = panels["Worker readiness"]["targets"][0]["expr"]
    service = panels["Service readiness"]["targets"][0]["expr"]
    assert 'up{job="vetmanager-availability"} == 1' in ready
    assert "vetmanager_worker_ready" in service and "vetmanager_service_healthz" in service
    assert 'count(vetmanager_worker_ready{job="vetmanager-availability"}) == 3' in service
    assert "vetmanager_probe_unknown" in panels["Probe unknown"]["targets"][0]["expr"]
    assert "or vector(0)" not in ready + service


def test_deploy_starts_probe_and_restores_or_stops_it_on_rollback() -> None:
    source = (ROOT / "scripts/stage385_deploy.py").read_text()
    assert '"--no-build", "availability-probe", timeout=180' in source
    assert 'if "availability-probe" in old_services:' in source
    assert '_compose(old_compose, project, old_image, "up", "-d", "--no-build"' in source
    assert '"stop", "availability-probe", timeout=60' in source


def test_probe_requires_bearer_and_never_accepts_dynamic_target(monkeypatch) -> None:
    from scripts import availability_probe as probe
    seen = []
    def fake_get(url: str, timeout: float):
        seen.append(url)
        return 200, ({"status": "ok", "probe": "liveness"} if url.endswith("healthz")
                     else {"status": "ok", "probe": "readiness"})
    monkeypatch.setattr(probe, "_fetch_json", fake_get)
    body = probe.collect("https://example.org", "secret", "Bearer secret")
    assert 'vetmanager_worker_ready{slot="mcp"} 1' in body
    assert 'vetmanager_worker_ready{slot="mcp2"} 1' in body
    assert 'vetmanager_worker_ready{slot="mcp3"} 1' in body
    assert "vetmanager_service_healthz 1" in body
    assert len(seen) == 4
    assert all("secret" not in url for url in seen)
    assert probe.collect("https://example.org", "secret", "Bearer bad") is None


def test_probe_transport_failure_is_unknown_not_target_down(monkeypatch) -> None:
    from scripts import availability_probe as probe
    monkeypatch.setattr(probe, "_fetch_json", lambda url, timeout: None)
    body = probe.collect("https://example.org", "secret", "Bearer secret")
    assert 'vetmanager_probe_unknown{slot="mcp"} 1' in body
    assert 'vetmanager_probe_unknown{slot="service"} 1' in body
    assert "vetmanager_worker_ready{slot=" not in body
    assert "vetmanager_service_healthz 0" not in body


def test_probe_accepts_valid_health_json_larger_than_one_kib(monkeypatch) -> None:
    from scripts import availability_probe as probe
    payload = json.dumps({"status": "ok", "probe": "readiness", "padding": "x" * 2048}).encode()
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, limit): return payload[:limit]
    monkeypatch.setattr(probe, "urlopen", lambda request, timeout: Response())
    assert probe._fetch_json("http://mcp:8000/readyz", 4) == (200, json.loads(payload))


def _samples(states: str, *, spacing: int = 15) -> list[Sample]:
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    return [Sample(start + timedelta(seconds=i * spacing), "worker", "slot1", state)
            for i, state in enumerate(states.split())]


def test_duration_is_bounded_by_last_success_first_failure_last_failure_first_recovery() -> None:
    events = classify_incidents(_samples("ok fail fail fail ok", spacing=900), cadence_seconds=900)
    assert len(events) == 1
    assert events[0].observed_failure_span_seconds == 1800
    assert events[0].outer_window_seconds == 3600
    assert events[0].verdict == "uncertain"
    assert events[0].start_confirmed and events[0].recovery_confirmed


def test_over_30_minutes_requires_strictly_greater_lower_bound() -> None:
    events = classify_incidents(_samples("ok fail fail fail fail ok", spacing=900), cadence_seconds=900)
    assert events[0].observed_failure_span_seconds == 2700
    assert events[0].verdict == "observed_over_30m"


def test_open_edges_and_gaps_do_not_invent_precision() -> None:
    left = classify_incidents(_samples("fail fail fail fail", spacing=900), cadence_seconds=900)[0]
    assert left.observed_failure_span_seconds == 2700 and left.outer_window_seconds is None
    assert not left.start_confirmed and not left.recovery_confirmed
    assert left.verdict == "observed_over_30m"
    gap = classify_incidents(_samples("ok fail missing fail ok", spacing=900), cadence_seconds=900)
    assert len(gap) == 2
    assert all(event.verdict == "uncertain" for event in gap)


def test_snapshot_rejects_extra_columns_and_monitor_conflicts(tmp_path: Path) -> None:
    snapshot = tmp_path / "sample.csv"
    snapshot.write_text("timestamp,signal,slot,state,client\n2026-11-01T00:00:00Z,worker,slot1,ok,123\n")
    with pytest.raises(ValueError, match="columns"):
        load_snapshot(snapshot)
    snapshot.write_text("timestamp,signal,slot,state\n"
                        "2026-11-01T00:00:00Z,monitor,service,missing\n"
                        "2026-11-01T00:00:00Z,worker,slot1,ok\n")
    with pytest.raises(ValueError, match="conflicts"):
        load_snapshot(snapshot)
    snapshot.write_text("timestamp,signal,slot,state\n"
                        "2026-11-01T00:00:00Z,monitor,service,missing\n"
                        "2026-11-01T00:00:15Z,worker,slot1,fail\n"
                        "2026-11-01T00:01:00Z,monitor,service,ok\n")
    with pytest.raises(ValueError, match="conflicts"):
        load_snapshot(snapshot)


def test_monitor_only_snapshot_reports_unknown_target_coverage(monkeypatch, tmp_path: Path, capsys) -> None:
    from scripts import stage464_downtime as downtime
    snapshot = tmp_path / "monitor-only.csv"
    snapshot.write_text("timestamp,signal,slot,state\n"
                        "2026-11-01T00:00:00Z,monitor,service,ok\n")
    monkeypatch.setattr(sys, "argv", ["stage464_downtime", str(snapshot),
                                    "--source", "curator-prometheus", "--cadence-seconds", "15",
                                    "--period-start", "2026-11-01T00:00:00Z",
                                    "--period-end", "2026-11-01T00:01:00Z"])
    assert downtime.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["coverage_status"] == "unknown_no_target_samples"
    assert report["target_sample_count"] == 0


def test_probe_rejects_non_https_or_credentialed_target() -> None:
    from scripts.availability_probe import _service_health_url
    for value in ("http://example.org", "https://user@example.org", "https://example.org/secret",
                  "https://example.org?token=x"):
        with pytest.raises(ValueError):
            _service_health_url(value)

"""Every process counter/latency recorder must publish to the shared store."""

import fakeredis
import pytest

import service_metrics as metrics
from shared_metric_counters import (
    RedisMetricCounters, SHARED_COUNTER_FAMILIES, SHARED_LATENCY_FAMILIES,
    wait_pending,
)


def test_all_recorders_reach_a_shared_family(monkeypatch):
    counters = []
    latencies = []
    monkeypatch.setattr(metrics, "_record_shared_counter",
                        lambda family, *_args: counters.append(family))
    monkeypatch.setattr(metrics, "_record_shared_latency",
                        lambda family, *_args: latencies.append(family))

    metrics.record_http_request(route="/readyz", method="GET", status_code=200,
                                duration_seconds=.01)
    metrics.record_auth_failure(source="bearer", reason="missing_authorization")
    metrics.record_upstream_failure(target="client", reason="timeout")
    metrics.record_upstream_request(target="client", status="200", duration_seconds=.01)
    metrics.record_tool_call(endpoint="/rest/api/client#list", method="GET",
                             outcome="success", duration_seconds=.01)
    metrics.record_sentry_delivery_lost("timeout")
    metrics.record_sentry_delivery_accepted(1)
    metrics.record_known_issue_lookup(tool_name="get_clients", outcome="no_match")
    metrics.record_prompt_request(method="get", prompt="welcome",
                                  allowed_names=frozenset({"welcome"}))
    metrics.record_token_expiry_notice_issued(1)
    metrics.record_token_expiry_notice_skipped("ineligible")
    metrics.record_token_preset_issued("full_access")
    metrics.record_placeholder_argument_rejection("get_clients")
    metrics.record_rate_limit_backend_degraded("redis_unavailable")
    metrics.record_sanitizer_failure()
    metrics.record_rest_unmapped_read()
    metrics.record_report_export_download(outcome="success")
    metrics.record_report_export_serve(outcome="served")
    metrics.record_report_ai_long_queued_poll()
    metrics.record_report_ai_stage_stall_poll()
    metrics.record_report_ai_job_created(outcome="success")
    metrics.record_report_ai_save_attempt(outcome="success")
    metrics.record_report_ai_job_transition(from_stage="queued", to_stage="ready")
    metrics.record_report_ai_job_terminal_outcome(outcome="completed", duration_seconds=.01)
    metrics.record_report_ai_empty_preview_guidance(first=True)
    metrics.record_report_ai_empty_preview_outcome(outcome="saved_empty")
    metrics.record_report_ai_job_stage_duration(stage="queued", duration_seconds=.01)
    metrics.record_report_ai_export(operation="start", outcome="success")
    metrics.record_report_ai_outcome_code(operation="job", code="unknown")
    metrics.record_report_ai_export_duration(outcome="success", duration_seconds=.01)
    metrics.record_business_event("bearer_token_issued")

    # Cache events originate in request_cache and are exercised separately by
    # test_stage385_shared_metric_counters.py.
    cache_families = {"cache_hits_total", "cache_misses_total",
                      "cache_invalidations_total", "cache_evictions_total"}
    assert set(counters) == SHARED_COUNTER_FAMILIES - cache_families
    assert set(latencies) == SHARED_LATENCY_FAMILIES


def test_metrics_help_type_cover_samples_without_process_claims():
    lines = metrics.render_prometheus_metrics().splitlines()
    helps = [line.split(" ", 3)[2] for line in lines if line.startswith("# HELP ")]
    types = [line.split(" ", 3)[2] for line in lines if line.startswith("# TYPE ")]
    assert len(helps) == len(set(helps))
    assert len(types) == len(set(types))
    assert set(helps) == set(types)
    for line in lines:
        if line.startswith("# HELP "):
            assert "process-local" not in line.lower()
            assert "in this process" not in line.lower()
        elif line and not line.startswith("#"):
            name = line.split("{", 1)[0].split(" ", 1)[0]
            base = name.rsplit("_", 1)[0]
            assert name in types or (name.endswith(("_count", "_sum", "_max"))
                                     and base in types)
            assert 'pid="' not in line and 'worker="' not in line


@pytest.mark.asyncio
async def test_rare_counter_events_reach_the_same_redis_snapshot(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(metrics.shared_metric_counters, "get_backend", lambda: backend)
    metrics.record_token_expiry_notice_skipped("ineligible")
    metrics.record_placeholder_argument_rejection("get_clients")
    metrics.record_report_export_serve(outcome="served")
    metrics.record_report_ai_job_created(outcome="success")
    metrics.record_sentry_delivery_lost("timeout")
    metrics.record_known_issue_lookup(tool_name="get_clients", outcome="no_match")
    metrics.record_business_event("bearer_token_issued")
    assert await wait_pending()
    snapshot = backend.snapshot()
    for family, key in (
        ("token_expiry_notice_skipped_total", "ineligible"),
        ("placeholder_argument_rejections_total", "get_clients"),
        ("report_export_serve_total", "served"),
        ("report_ai_jobs_total", "success"),
        ("sentry_delivery_lost_total", "timeout"),
        ("known_issue_lookups_total", "get_clients|no_match|failure"),
        ("business_events_total", "bearer_token_issued"),
    ):
        assert snapshot[family][key] == 1

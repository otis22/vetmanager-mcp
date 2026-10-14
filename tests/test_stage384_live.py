"""Devtr6 latency and memory measurement on the isolated live-server fixture."""

import concurrent.futures
import json
import os
from pathlib import Path
import resource
import time

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from bearer_token_manager import generate_bearer_token
from rate_limit_backend import reset_rate_limit_backend
import service_metrics
from service_metrics import snapshot_service_metrics
from shared_metric_counters import SharedMetricsUnavailable
from storage import normalize_database_url_for_migrations
from storage_models import Account, ServiceBearerToken, VetmanagerConnection
from tool_access_registry import PRESET_FULL_ACCESS, get_token_preset_scopes
from tests.test_e2e_real import _post_with_csrf_sync


pytestmark = pytest.mark.real_api


def seed_devtr6_bearer() -> str:
    token = generate_bearer_token()
    engine = create_engine(normalize_database_url_for_migrations(os.environ["DATABASE_URL"]))
    with Session(engine) as session:
        account = Account(email="stage384-load@example.test", status="active")
        session.add(account)
        session.flush()
        connection = VetmanagerConnection(
            account_id=account.id, auth_mode="domain_api_key", status="active",
            domain=os.environ["TEST_DOMAIN"],
        )
        connection.set_credentials(
            {"domain": os.environ["TEST_DOMAIN"], "api_key": os.environ["TEST_API_KEY"]},
            encryption_key=os.environ["STORAGE_ENCRYPTION_KEY"],
        )
        bearer = ServiceBearerToken(account_id=account.id, name="Stage 384 latency probe")
        bearer.set_raw_token(token)
        bearer.set_scopes(get_token_preset_scopes(PRESET_FULL_ACCESS))
        session.add_all([connection, bearer])
        session.commit()
    engine.dispose()
    return token


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="devtr6 credentials absent")
def test_devtr6_tools_list_200_request_probe(live_server_url, prepared_web_db):
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=30) as client:
        for route in ("/healthz", "/readyz"):
            response = client.get(route)
            assert response.status_code == 200
            print("PROBE", route, response.status_code)

    def run_client(index):
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        }
        timings, statuses = [], []
        with httpx.Client(base_url=live_server_url, timeout=30) as client:
            initialized = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": index + 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage384-load", "version": "1"}},
            })
            assert initialized.status_code == 200
            headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
            ready = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            })
            assert ready.status_code in (200, 202)
            for n in range(20):
                request_id = 100 + index * 20 + n
                start = time.monotonic()
                response = client.post("/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": request_id, "method": "tools/list",
                })
                timings.append((time.monotonic() - start) * 1000)
                if "text/event-stream" in response.headers.get("content-type", ""):
                    payloads = [json.loads(line[6:]) for line in response.text.splitlines()
                                if line.startswith("data: ")]
                    body = next((item for item in payloads if item.get("id") == request_id), None)
                else:
                    body = response.json()
                assert body is not None and body.get("id") == request_id
                assert "error" not in body and isinstance(body.get("result", {}).get("tools"), list)
                statuses.append(response.status_code)
        return timings, statuses

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        samples = list(pool.map(run_client, range(10)))
    times = [value for timings, _ in samples for value in timings]
    codes = [code for _, statuses in samples for code in statuses]
    assert len(codes) == 200 and all(code == 200 for code in codes)
    rss_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    cgroup_peak_path = Path("/sys/fs/cgroup/memory.peak")
    cgroup_peak = int(cgroup_peak_path.read_text()) if cgroup_peak_path.exists() else None
    current_path = Path("/sys/fs/cgroup/memory.current")
    limit_path = Path("/sys/fs/cgroup/memory.max")
    events_path = Path("/sys/fs/cgroup/memory.events")
    cgroup_current = int(current_path.read_text()) if current_path.exists() else None
    raw_limit = limit_path.read_text().strip() if limit_path.exists() else "max"
    events = dict(line.split() for line in events_path.read_text().splitlines()) if events_path.exists() else {}
    print("STAGE384_DEVTR6", json.dumps({
        "requests": len(codes), "success": codes.count(200), "errors": 0,
        "p95_ms": round(sorted(times)[189], 2), "test_process_peak_rss_bytes": rss_peak,
        "test_container_peak_bytes": cgroup_peak, "test_container_current_bytes": cgroup_current,
        "test_container_limit": raw_limit, "oom": int(events.get("oom", 0)),
        "oom_kill": int(events.get("oom_kill", 0)), "measurement_scope": "pytest+live_server",
    }))


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="devtr6 contour absent")
def test_devtr6_fixture_fails_closed_when_redis_is_unavailable(live_server_url, prepared_web_db, monkeypatch):
    assert "pytest" in str(prepared_web_db)
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("RATE_LIMIT_REQUIRE_REDIS", "1")
    reset_rate_limit_backend()
    before = service_metrics._RATE_LIMIT_BACKEND_DEGRADED_TOTAL.get("strict_failure", 0)
    try:
        with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=10) as client:
            response = _post_with_csrf_sync(client, "/register", data={
                "email": "stage384-redis-failure@example.test", "password": "Stage384-local-pass-123",
            })
        assert response.status_code == 500
        with pytest.raises(SharedMetricsUnavailable):
            snapshot_service_metrics()
        after = service_metrics._RATE_LIMIT_BACKEND_DEGRADED_TOTAL.get("strict_failure", 0)
        assert after > before
        print("STAGE384_REDIS_FAIL_CLOSED", response.status_code, "strict_failure_delta", after - before)
    finally:
        reset_rate_limit_backend()

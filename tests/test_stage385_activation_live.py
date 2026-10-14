"""Opt-in devtr6 activation snapshot through three isolated MCP slots."""

import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import redis
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from shared_metric_counters import (
    ACTIVATION_ALERTS_KEY, ACTIVATION_SCAN_LEASE_KEY, ACTIVATION_SNAPSHOT_KEY,
)
from storage import normalize_database_url_for_migrations
from storage_models import ServiceBearerToken
from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_activation_snapshot_is_identical_on_three_slots(prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    seed_devtr6_bearer()
    engine = create_engine(normalize_database_url_for_migrations(os.environ["DATABASE_URL"]))
    with Session(engine) as session:
        bearer = session.scalar(select(ServiceBearerToken))
        assert bearer is not None
        bearer.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        session.commit()
    engine.dispose()
    redis_client = redis.Redis.from_url(os.environ["STAGE385_REDIS_URL"])
    redis_client.delete(ACTIVATION_SCAN_LEASE_KEY, ACTIVATION_SNAPSHOT_KEY,
                        ACTIVATION_ALERTS_KEY)
    env = os.environ.copy()
    env.update(REDIS_URL=env["STAGE385_REDIS_URL"], MCP_WORKER_SLOTS="3",
               DB_POOL_SIZE="8", DB_MAX_OVERFLOW="5", LOG_FORMAT="text",
               METRICS_AUTH_TOKEN="stage385-isolated-metrics")
    processes = []
    clients = []
    completed = False
    try:
        for port in (_free_port(), _free_port(), _free_port()):
            env["PORT"] = str(port)
            processes.append(subprocess.Popen(
                [sys.executable, "-c", "from server import _run_http_server; import os; "
                 "_run_http_server(transport='streamable-http',host='127.0.0.1',"
                 "port=int(os.environ['PORT']),path='/mcp')"],
                cwd=Path(__file__).resolve().parents[1], env=env.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            ))
            clients.append(httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30))
        for client, process in zip(clients, processes):
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError("MCP slot exited before readiness")
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("MCP slot did not become ready")
        headers = {"Authorization": "Bearer stage385-isolated-metrics"}
        bodies = []
        for client in clients:
            response = client.get("/metrics", headers=headers)
            assert response.status_code == 200
            bodies.append(response.text)
        prefix = "vetmanager_account_last_request_age_avg_hours "
        values = [[line for line in body.splitlines() if line.startswith(prefix)]
                  for body in bodies]
        assert all(len(value) == 1 for value in values)
        assert values[0] == values[1] == values[2]
        assert all("account_id=" not in body for body in bodies)
        assert redis_client.exists(ACTIVATION_SCAN_LEASE_KEY)
        redis_client.delete(ACTIVATION_SCAN_LEASE_KEY)
        handoff = clients[2].get("/metrics", headers=headers)
        assert handoff.status_code == 200
        handoff_values = [line for line in handoff.text.splitlines() if line.startswith(prefix)]
        assert len(handoff_values) == 1
        assert abs(float(handoff_values[0].rsplit(" ", 1)[1]) -
                   float(values[0][0].rsplit(" ", 1)[1])) < .01
        print("STAGE385_ACTIVATION", {"slots": 3, "http_codes": [200] * 3,
                                      "shared_age_gauge": True, "scan_lease": True,
                                      "owner_handoff_http": 200})
        completed = True
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
        if completed:
            warnings = sum(process.stderr.read().count("account_traffic_silent")
                           for process in processes)
            assert warnings == 1
            print("STAGE385_ACTIVATION_ALERT", {"warning_count": warnings})

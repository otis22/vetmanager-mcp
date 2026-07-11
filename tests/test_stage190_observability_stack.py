"""Stage 190 Prometheus/Grafana observability stack tests."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml
import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
PROMETHEUS_CONFIG = REPO_ROOT / "ops" / "prometheus" / "prometheus.yml"
GRAFANA_DATASOURCE = (
    REPO_ROOT / "ops" / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
)
GRAFANA_DASHBOARD = REPO_ROOT / "ops" / "grafana" / "dashboards" / "vetmanager-overview.json"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_server.sh"


def _compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_stage190_compose_config_validates_with_required_grafana_secret() -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI is not available in the test container")
    result = subprocess.run(
        ["docker", "compose", "--profile", "production", "config"],
        cwd=REPO_ROOT,
        env={**os.environ, "GRAFANA_ADMIN_PASSWORD": "stage190-not-default"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_stage190_observability_services_are_localhost_only_and_persistent() -> None:
    compose = _compose()
    services = compose["services"]

    assert {"prometheus", "grafana"}.issubset(services)
    assert services["mcp"]["environment"]["PORT"] == 8000
    assert services["mcp"]["ports"] == ["127.0.0.1:${PORT:-8000}:8000"]
    assert services["prometheus"]["ports"] == ["127.0.0.1:${PROMETHEUS_PORT:-9090}:9090"]
    assert services["grafana"]["ports"] == ["127.0.0.1:${GRAFANA_PORT:-3000}:3000"]
    assert "prometheus-data" in compose["volumes"]
    assert "grafana-data" in compose["volumes"]
    assert any("prometheus-data:/prometheus" in volume for volume in services["prometheus"]["volumes"])
    assert any("grafana-data:/var/lib/grafana" in volume for volume in services["grafana"]["volumes"])


def test_stage190_observability_security_and_resource_limits() -> None:
    services = _compose()["services"]
    prometheus = services["prometheus"]
    grafana = services["grafana"]
    prometheus_entrypoint = prometheus["entrypoint"]
    prometheus_command = prometheus_entrypoint[2]

    assert prometheus_entrypoint[:2] == ["/bin/sh", "-c"]
    assert "--storage.tsdb.retention.time=30d" in prometheus_command
    assert "--storage.tsdb.retention.size=1GB" in prometheus_command
    assert "printenv METRICS_AUTH_TOKEN > /tmp/metrics_bearer_token" in prometheus_command
    assert "$${METRICS_AUTH_TOKEN" not in prometheus_command
    assert prometheus["cpus"] == "0.5"
    assert prometheus["mem_limit"] == "384m"
    assert grafana["cpus"] == "0.5"
    assert grafana["mem_limit"] == "256m"
    assert prometheus["deploy"]["resources"]["limits"]["memory"]
    assert grafana["deploy"]["resources"]["limits"]["memory"]
    assert grafana["environment"]["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert grafana["environment"]["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert grafana["environment"]["GF_SECURITY_ADMIN_PASSWORD"] == "${GRAFANA_ADMIN_PASSWORD:-}"


def test_stage190_prometheus_scrapes_mcp_with_bearer_token_file() -> None:
    config = yaml.safe_load(PROMETHEUS_CONFIG.read_text(encoding="utf-8"))
    scrape = config["scrape_configs"][0]

    assert scrape["job_name"] == "vetmanager-mcp"
    assert scrape["metrics_path"] == "/metrics"
    assert scrape["bearer_token_file"] == "/tmp/metrics_bearer_token"
    assert scrape["static_configs"][0]["targets"] == ["mcp:8000"]
    assert "METRICS_AUTH_TOKEN" not in PROMETHEUS_CONFIG.read_text(encoding="utf-8")


def test_stage190_grafana_provisioning_and_dashboard_queries_are_safe() -> None:
    datasource = yaml.safe_load(GRAFANA_DATASOURCE.read_text(encoding="utf-8"))["datasources"][0]
    dashboard = json.loads(GRAFANA_DASHBOARD.read_text(encoding="utf-8"))

    assert datasource["name"] == "Prometheus"
    assert datasource["uid"] == "Prometheus"
    assert datasource["url"] == "http://prometheus:9090"
    panel_titles = {panel["title"] for panel in dashboard["panels"]}
    panel_ids = [panel["id"] for panel in dashboard["panels"]]
    assert {
        "Top tool calls",
        "Tool call rate",
        "Tool error rate",
        "Upstream statuses",
        "Business events",
        "Activation telemetry",
        "Activation funnel",
        "New account activation funnel",
        "Integration failures by reason/device",
    }.issubset(panel_titles)
    tool_error_panel = next(
        panel for panel in dashboard["panels"] if panel["title"] == "Tool error rate"
    )
    tool_error_expr = tool_error_panel["targets"][0]["expr"]
    assert 'vetmanager_tool_calls_total{outcome="error"}' in tool_error_expr
    assert "or vector(0)" in tool_error_expr
    assert "clamp_min" in tool_error_expr
    assert "1e-9" in tool_error_expr
    activation_telemetry_panel = next(
        panel for panel in dashboard["panels"] if panel["title"] == "Activation telemetry"
    )
    activation_telemetry_exprs = {
        target["expr"] for target in activation_telemetry_panel["targets"]
    }
    assert (
        "(avg(vetmanager_account_last_request_age_hours) or vector(0))"
        in activation_telemetry_exprs
    )
    assert (
        "(count(vetmanager_account_last_request_age_hours) or vector(0))"
        in activation_telemetry_exprs
    )
    new_account_funnel_panel = next(
        panel for panel in dashboard["panels"] if panel["title"] == "New account activation funnel"
    )
    new_account_funnel_expr = new_account_funnel_panel["targets"][0]["expr"]
    assert "token_copied" not in new_account_funnel_expr
    assert len(panel_ids) == len(set(panel_ids))
    occupied_cells: set[tuple[int, int]] = set()
    for panel in dashboard["panels"]:
        pos = panel["gridPos"]
        cells = {
            (x, y)
            for x in range(pos["x"], pos["x"] + pos["w"])
            for y in range(pos["y"], pos["y"] + pos["h"])
        }
        assert not (occupied_cells & cells), panel["title"]
        occupied_cells.update(cells)

    text = GRAFANA_DASHBOARD.read_text(encoding="utf-8")
    forbidden = ("email", "clinic", "customer", "client_name", "phone", "token_prefix")
    assert not any(word in text.lower() for word in forbidden)

    allowed_labels = {
        "endpoint",
        "tool",
        "method",
        "outcome",
        "target",
        "status",
        "event",
        "stage",
        "device",
        "auth_mode",
        "reason",
    }
    label_names = set(re.findall(r"(?:by|without) \(([^)]*)\)", text))
    flattened = {
        label.strip()
        for group in label_names
        for label in group.split(",")
        if label.strip()
    }
    assert flattened <= allowed_labels


def test_stage190_deploy_script_guards_grafana_password_and_warns_observability() -> None:
    text = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "GRAFANA_ADMIN_PASSWORD must be set to a non-default secret value" in text
    assert "METRICS_AUTH_TOKEN must be set before production deploy" in text
    assert '""|admin|password|changeme|CHANGE_ME)' in text
    assert "METRICS_AUTH_TOKEN_LINE" in text
    assert "export METRICS_AUTH_TOKEN" in text
    assert "compose up -d --no-build prometheus grafana" in text
    assert "observability services failed to start; app deploy remains complete" in text
    assert "prometheus_mcp_target_is_up()" in text
    assert 'target.get("scrapePool") == "vetmanager-mcp"' in text
    assert 'target.get("health") == "up"' in text
    assert "Prometheus target health is not up yet" in text
    assert "api/datasources/name/Prometheus" in text
    assert "api/dashboards/uid/vetmanager-mcp-overview" in text
    assert "curl -fsS -u" not in text
    assert "grafana_api_check()" in text
    assert "must not contain double quote or backslash" in text

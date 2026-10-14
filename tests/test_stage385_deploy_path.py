"""The canonical deploy must stage, pin rollback, drain, and cut over all slots."""

from pathlib import Path
import json
import secrets
import tarfile

import pytest
import yaml

from scripts.stage385_release import make_rollback_manifest
from scripts import stage385_deploy
from scripts.stage385_deploy import render_nginx_site


ROOT = Path(__file__).resolve().parents[1]


def test_workflow_uses_staged_release_only():
    workflow = (ROOT / ".github/workflows/deploy-prod.yml").read_text()
    assert "scripts.stage385_release stage" in workflow
    assert "scripts.stage385_deploy" in workflow
    assert "rsync -az --delete" not in workflow
    assert "./scripts/deploy_server.sh" not in workflow


def test_legacy_deploy_fails_closed():
    source = (ROOT / "scripts/deploy_server.sh").read_text()
    assert "Legacy single-slot deploy is disabled" in source
    assert "docker build" not in source


def test_rollback_manifest_pins_all_previous_slots():
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    image = "sha256:" + "b" * 64
    manifest = make_rollback_manifest(compose, image, "vetmanager-mcp", slot_count=3)
    assert {"mcp", "mcp2", "mcp3"} <= manifest["services"].keys()
    for name in ("mcp", "mcp2", "mcp3"):
        assert manifest["services"][name]["image"] == image
        assert "build" not in manifest["services"][name]
        assert "MCP_WORKER_SLOTS=3" in manifest["services"][name]["environment"]


PROD_SITE = """server {
    server_name old.example;
    location / {
        proxy_pass http://127.0.0.1:8000;
    }
    listen 443 ssl;
    ssl_certificate /etc/letsencrypt/live/old.example/fullchain.pem;
}
server {
    listen 80;
    return 301 https://$host$request_uri;
}
"""


def test_nginx_candidate_preserves_tls_and_gates_all_routes():
    maintenance = render_nginx_site(PROD_SITE, "maintenance")
    active = render_nginx_site(PROD_SITE, "active")
    assert "return 503" in maintenance
    assert "proxy_pass" not in maintenance
    assert "old.example/fullchain.pem" in active
    assert "hash $http_authorization consistent;" in active
    assert all(f"server 127.0.0.1:{port};" in active for port in (8000, 8001, 8002))
    assert "location /mcp" in active
    assert "old.example/fullchain.pem" in maintenance
    with pytest.raises(ValueError):
        render_nginx_site("server { location / { return 200; } }", "active")


def _simulate_cutover(monkeypatch, tmp_path, *, fail_ready=False, repeat=False):
    live = tmp_path / "live"
    release = live / "releases" / ("a" * 40)
    release.mkdir(parents=True)
    (live / "docker-compose.yml").write_text((ROOT / "docker-compose.yml").read_text())
    (release / "docker-compose.yml").write_text((ROOT / "docker-compose.yml").read_text())
    (live / ".env").write_text(
        "FEEDBACK_FINGERPRINT_PEPPER=old\n"
        f"GRAFANA_ADMIN_PASSWORD={secrets.token_hex(24)}\n"
        f"METRICS_AUTH_TOKEN={secrets.token_hex(24)}\n")
    site = tmp_path / "site.conf"
    site.write_text(render_nginx_site(PROD_SITE, "active") if repeat else PROD_SITE)
    old_image = "sha256:" + "b" * 64
    new_image = "sha256:" + "c" * 64
    if repeat:
        previous = live / "releases" / ("d" * 40)
        previous.mkdir()
        (previous / "docker-compose.yml").write_text((ROOT / "docker-compose.yml").read_text())
        state_dir = live / "release-state"
        state_dir.mkdir()
        (state_dir / "base-nginx.conf").write_text(PROD_SITE)
        (state_dir / "current.json").write_text(json.dumps({"release": str(previous), "image": old_image}))
    events = []
    monkeypatch.setattr(stage385_deploy, "_project_and_image", lambda: ("probe", old_image))

    def run(*args, **kw):
        events.append(("run", args))
        if args[:2] == ("bash", "scripts/post_deploy_smoke_checks.sh"):
            events.append(("smoke_token", bool(kw["env"].get("METRICS_AUTH_TOKEN"))))
        if args[:3] == ("docker", "image", "inspect"):
            return new_image
        return old_image if args[:2] == ("docker", "inspect") else ""

    monkeypatch.setattr(stage385_deploy, "_run", run)
    monkeypatch.setattr(stage385_deploy, "_container", lambda project, service: service)
    monkeypatch.setattr(stage385_deploy, "_compose", lambda path, project, image, *args, **kw: (
        events.append(("compose", path.name, image, args)) or
        (json.dumps({"services": {"mcp": {"environment": {
            "METRICS_AUTH_TOKEN": secrets.token_hex(24)}}}})
         if args == ("config", "--format", "json") else "")))
    monkeypatch.setattr(stage385_deploy, "_backup_pg", lambda project, bundle: (
        events.append(("backup",)) or bundle / "backup"))
    monkeypatch.setattr(stage385_deploy, "_write_site", lambda candidate, path: (
        events.append(("nginx", "maintenance" if "return 503" in candidate else
                       "active" if "mcp_session_backend" in candidate else "old")) or
        path.write_text(candidate)))
    monkeypatch.setattr(stage385_deploy, "_stop_old", lambda *args: events.append(("stop_old",)))

    def ready(port):
        events.append(("ready", port))
        if fail_ready and port == 8001:
            raise TimeoutError("slot failed")

    monkeypatch.setattr(stage385_deploy, "_ready", ready)
    if fail_ready:
        with pytest.raises(TimeoutError, match="slot failed"):
            stage385_deploy.deploy(release, live, release.name, site=site, pepper="new")
    else:
        stage385_deploy.deploy(release, live, release.name, site=site, pepper="new")
    bundle = live / "release-state" / "rollback" / release.name
    manifest = yaml.safe_load((bundle / "rollback.yml").read_text())
    assert manifest["services"]["mcp"]["image"] == old_image
    if repeat:
        assert all(manifest["services"][name]["image"] == old_image for name in ("mcp2", "mcp3"))
    assert bundle.is_relative_to(live) and not bundle.is_relative_to(release)
    if not repeat:
        with tarfile.open(bundle / "old-source.tar.gz") as archive:
            assert "docker-compose.yml" in archive.getnames()
            assert ".env" not in archive.getnames()
    assert events.index(("backup",)) < events.index(("nginx", "maintenance"))
    assert events.index(("nginx", "maintenance")) < events.index(("stop_old",))
    assert events.index(("stop_old",)) < events.index(("ready", 8000))
    return events, site, old_image


def test_cutover_waits_for_three_slots_before_nginx(monkeypatch, tmp_path):
    events, site, _ = _simulate_cutover(monkeypatch, tmp_path)
    assert events.index(("ready", 8002)) < events.index(("nginx", "active"))
    assert ("smoke_token", True) in events
    assert "mcp_session_backend" in site.read_text()


def test_failed_cutover_rolls_back_pinned_image(monkeypatch, tmp_path):
    events, site, old_image = _simulate_cutover(monkeypatch, tmp_path, fail_ready=True)
    assert any(e[:3] == ("compose", "rollback.yml", old_image) and "up" in e[3] for e in events)
    assert events[-1] == ("nginx", "old")
    assert site.read_text() == PROD_SITE


def test_repeat_release_keeps_three_slot_rollback(monkeypatch, tmp_path):
    events, site, old_image = _simulate_cutover(monkeypatch, tmp_path, repeat=True)
    assert "mcp_session_backend" in site.read_text()
    assert any(e == ("compose", "rollback.yml", old_image, ("config", "--quiet")) for e in events)

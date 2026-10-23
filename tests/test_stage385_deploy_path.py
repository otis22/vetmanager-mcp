"""The canonical deploy must stage, pin rollback, drain, and cut over all slots."""

from pathlib import Path
import json
import io
import secrets
import tarfile
import urllib.error

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
    steps = yaml.safe_load(workflow)["jobs"]["deploy"]["steps"]
    public = next(step for step in steps if step.get("id") == "public_smoke")
    alert = next(step for step in steps if step.get("name") == "Alert on public smoke failure")
    assert public["continue-on-error"] is True
    assert "server_name" not in public["run"]
    assert "python scripts/post_deploy_mcp_tool_smoke.py" in public["run"]
    assert "public_smoke.outcome == 'failure'" in alert["if"]


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


def test_local_nginx_smoke_rejects_missing_mcp_and_redirect(monkeypatch):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return b'{"status":"ok"}'

    class Opener:
        def __init__(self, mcp_status):
            self.mcp_status = mcp_status
            self.urls = []

        def open(self, request, timeout):
            self.urls.append(request.full_url)
            if request.full_url.endswith("/mcp"):
                raise urllib.error.HTTPError(request.full_url, self.mcp_status,
                                             "failed", {}, io.BytesIO())
            return Response()

    for status in (302, 404):
        opener = Opener(status)
        handlers = []

        def build_opener(*args):
            handlers.extend(args)
            return opener

        monkeypatch.setattr(stage385_deploy.urllib.request, "build_opener", build_opener)
        with pytest.raises(TimeoutError, match="local nginx healthz"):
            stage385_deploy._nginx_local_smoke("old.example", seconds=0.1)
        assert opener.urls == ["https://127.0.0.1:443/healthz",
                               "https://127.0.0.1:443/mcp"]
        redirects = [handler for handler in handlers
                     if isinstance(handler, stage385_deploy.urllib.request.HTTPRedirectHandler)]
        assert len(redirects) == 1
        assert redirects[0].redirect_request(None, None, 302, "", {}, "https://elsewhere") is None


def _simulate_cutover(monkeypatch, tmp_path, *, fail_ready=False, fail_smoke=False,
                      fail_nginx=False, repeat=False, partial_new=False, fail_preflight=False):
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
            assert args[2:] == ("http://127.0.0.1:8000",)
            if fail_smoke:
                raise RuntimeError("injected internal smoke failure")
        if args[:3] == ("docker", "image", "inspect"):
            return new_image
        return old_image if args[:2] == ("docker", "inspect") else ""

    monkeypatch.setattr(stage385_deploy, "_run", run)
    monkeypatch.setattr(stage385_deploy, "_container", lambda project, service: service)
    def compose(path, project, image, *args, **kw):
        events.append(("compose", path.name, image, args))
        if path.name == "rollback.yml" and "up" in args:
            manifest = yaml.safe_load(path.read_text())
            for service in (("mcp", "mcp2", "mcp3") if repeat else ("mcp",)):
                assert any(isinstance(volume, dict) and volume.get("target") == "/app/.env"
                           and volume.get("source") == "./.env"
                           for volume in manifest["services"][service]["volumes"])
            assert (path.parent / ".env").resolve() == live / ".env"
        if args == ("config", "--format", "json"):
            return json.dumps({"services": {"mcp": {"environment": {
                "METRICS_AUTH_TOKEN": secrets.token_hex(24)}}}})
        return ""

    monkeypatch.setattr(stage385_deploy, "_compose", compose)
    monkeypatch.setattr(stage385_deploy, "_backup_pg", lambda project, bundle: (
        events.append(("backup",)) or bundle / "backup"))
    monkeypatch.setattr(stage385_deploy, "_write_site", lambda candidate, path: (
        events.append(("nginx", "maintenance" if "return 503" in candidate else
                       "active" if "mcp_session_backend" in candidate else "old")) or
        path.write_text(candidate)))
    def stop_old(project, slots, **kwargs):
        events.append(("stop_old",))
        events.append(("stop_slots", slots, kwargs.get("fence", False)))

    monkeypatch.setattr(stage385_deploy, "_stop_old", stop_old)
    monkeypatch.setattr(stage385_deploy, "_running_new_slots", lambda project, image: (
        ("mcp",) if partial_new else tuple(stage385_deploy.SLOTS)))

    def ready(port):
        events.append(("ready", port))
        if fail_ready and port == 8001:
            raise TimeoutError("slot failed")

    monkeypatch.setattr(stage385_deploy, "_ready", ready)
    def preflight(port):
        events.append(("protocol", port))
        if fail_preflight and port == 8001:
            raise RuntimeError("slot is not stateless")

    monkeypatch.setattr(stage385_deploy, "_stateless_protocol_ready", preflight)
    def nginx_smoke(hostname):
        events.append(("nginx_smoke", hostname))
        if fail_nginx:
            raise TimeoutError("local nginx route failed")

    monkeypatch.setattr(stage385_deploy, "_nginx_local_smoke", nginx_smoke)
    if fail_ready or fail_smoke or fail_nginx or fail_preflight:
        with pytest.raises((TimeoutError, RuntimeError),
                           match="slot failed|slot is not stateless|injected internal smoke failure|local nginx route failed"):
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
    assert events.index(("ready", 8002)) < events.index(("protocol", 8002))
    assert events.index(("protocol", 8002)) < events.index(("nginx", "active"))
    assert events.index(("nginx", "active")) < events.index(("nginx_smoke", "old.example"))
    assert ("smoke_token", True) in events
    assert "mcp_session_backend" in site.read_text()


def test_failed_cutover_rolls_back_pinned_image(monkeypatch, tmp_path):
    events, site, old_image = _simulate_cutover(monkeypatch, tmp_path, fail_ready=True)
    assert events.count(("stop_old",)) == 2
    rollback_index = next(i for i, e in enumerate(events)
                          if e[:3] == ("compose", "rollback.yml", old_image) and "up" in e[3])
    assert [i for i, e in enumerate(events) if e == ("stop_old",)][1] < rollback_index
    assert any(e[:3] == ("compose", "rollback.yml", old_image) and "up" in e[3] for e in events)
    assert events[-1] == ("nginx", "old")
    assert site.read_text() == PROD_SITE


def test_failed_smoke_automatically_restores_manifest_and_nginx(monkeypatch, tmp_path):
    events, site, old_image = _simulate_cutover(monkeypatch, tmp_path, fail_smoke=True)
    assert ("smoke_token", True) in events
    assert any(e[:3] == ("compose", "rollback.yml", old_image) and "up" in e[3]
               for e in events)
    assert events[-1] == ("nginx", "old")
    assert site.read_text() == PROD_SITE


def test_failed_local_nginx_route_automatically_rolls_back(monkeypatch, tmp_path):
    events, site, old_image = _simulate_cutover(monkeypatch, tmp_path, fail_nginx=True)
    assert ("nginx_smoke", "old.example") in events
    assert any(e[:3] == ("compose", "rollback.yml", old_image) and "up" in e[3]
               for e in events)
    assert site.read_text() == PROD_SITE


def test_repeat_release_keeps_three_slot_rollback(monkeypatch, tmp_path):
    events, site, old_image = _simulate_cutover(monkeypatch, tmp_path, repeat=True)
    assert "mcp_session_backend" in site.read_text()
    assert any(e == ("compose", "rollback.yml", old_image, ("config", "--quiet")) for e in events)


def test_partial_start_rolls_back_after_fencing_running_new_slot(monkeypatch, tmp_path):
    events, site, old_image = _simulate_cutover(monkeypatch, tmp_path, fail_ready=True,
                                                partial_new=True)
    fence = events.index(("stop_slots", ("mcp",), True))
    restore = next(i for i, e in enumerate(events)
                   if e[:3] == ("compose", "rollback.yml", old_image) and "up" in e[3])
    assert fence < restore
    assert site.read_text() == PROD_SITE


def test_partial_new_fleet_only_drains_started_slots(monkeypatch):
    image = "sha256:" + "c" * 64
    old = "sha256:" + "b" * 64
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        if args[:3] == ("docker", "ps", "-aq"):
            return {"mcp": "new-mcp", "mcp2": "old-mcp2", "mcp3": ""}[args[-1].split("=")[-1]]
        if args[:3] == ("docker", "inspect", "-f"):
            if args[3] == "{{.State.Running}}":
                return "true"
            return {"new-mcp": image, "old-mcp2": old}[args[-1]]
        return ""

    monkeypatch.setattr(stage385_deploy, "_run", run)
    assert stage385_deploy._running_new_slots("probe", image) == ("mcp",)
    assert not any(call[:3] == ("docker", "kill", "--signal=USR1") for call in calls)

    def exited(*args, **kwargs):
        if args[:3] == ("docker", "ps", "-aq"):
            return "new-mcp" if args[-1].endswith("=mcp") else ""
        if args[3] == "{{.State.Running}}":
            return "false"
        return image

    monkeypatch.setattr(stage385_deploy, "_run", exited)
    with pytest.raises(RuntimeError, match="without proven drain"):
        stage385_deploy._running_new_slots("probe", image)


def test_failed_stateless_preflight_keeps_maintenance_until_rollback(monkeypatch, tmp_path):
    events, site, _ = _simulate_cutover(monkeypatch, tmp_path, repeat=True,
                                        fail_preflight=True)
    assert ("protocol", 8000) in events and ("protocol", 8001) in events
    rollback = next(index for index, event in enumerate(events)
                    if event[0] == "compose" and event[1] == "rollback.yml"
                    and "up" in event[3])
    assert events.index(("protocol", 8001)) < rollback < events.index(("nginx", "active"))
    assert events.count(("stop_old",)) == 2
    assert "mcp_session_backend" in site.read_text()

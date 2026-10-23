#!/usr/bin/env python3
"""Fail-closed maintenance cutover for first and later three-slot releases."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

import yaml

from scripts.stage385_release import IMAGE_ID, SHA, make_rollback_manifest, write_rollback_manifest
from scripts.quiesce_mcp_slot import _drain_finished, _wait_write_fence
from scripts.update_env_secret import update_env_secret


SITE = Path("/etc/nginx/sites-available/vetmanager-mcp.conf")
SLOTS = {"mcp": 8000, "mcp2": 8001, "mcp3": 8002}
UPSTREAMS = """upstream mcp_backend {
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    keepalive 32;
}
upstream mcp_session_backend {
    hash $http_authorization consistent;
    server 127.0.0.1:8000;
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
    keepalive 32;
}
"""
ACTIVE_LOCATIONS = """    location = /metrics {
        allow 127.0.0.1;
        allow ::1;
        deny all;
        proxy_pass http://mcp_backend;
        proxy_set_header Authorization $http_authorization;
    }
    location /mcp {
        proxy_pass http://mcp_session_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;
        proxy_buffering off;
        proxy_read_timeout 3600s;
    }
    location / {
        proxy_pass http://mcp_backend;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
"""


def _run(*args: str, cwd: Path | None = None, env: dict | None = None,
         timeout: int = 120) -> str:
    return subprocess.run(args, cwd=cwd, env=env, timeout=timeout,
                          check=True, capture_output=True, text=True).stdout.strip()


def render_nginx_site(base: str, mode: str) -> str:
    """Transform the observed TLS site, preserving its Certbot directives."""
    if mode not in {"maintenance", "active"}:
        raise ValueError("Unknown nginx mode")
    if base.count("server {") != 2 or "ssl_certificate " not in base:
        raise ValueError("Unexpected production nginx site layout")
    if "proxy_pass http://127.0.0.1:8000;" not in base:
        raise ValueError("Base nginx site is not the observed single-slot site")
    first = base.index("server {")
    start = base.index("{", first)
    depth = 0
    end = None
    for offset in range(start, len(base)):
        if base[offset] == "{":
            depth += 1
        elif base[offset] == "}":
            depth -= 1
            if depth == 0:
                end = offset
                break
    if end is None:
        raise ValueError("Unbalanced nginx server block")
    body = base[start + 1:end]
    locations = list(re.finditer(r"(?m)^\s*location\s+[^{}]+\{[^{}]*\}\s*", body))
    if len(locations) != 1 or "location /" not in locations[0].group():
        raise ValueError("Unexpected base nginx locations")
    replacement = "    location / { return 503; }\n" if mode == "maintenance" else ACTIVE_LOCATIONS
    body = body[:locations[0].start()] + "\n" + replacement + body[locations[0].end():]
    result = base[:start + 1] + body + base[end:]
    return (UPSTREAMS + result) if mode == "active" else result


def _write_site(candidate: str, site: Path = SITE) -> None:
    old = site.read_text()
    mode = site.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile("w", dir=site.parent, prefix=".stage385-", delete=False) as handle:
        temp = Path(handle.name)
        handle.write(candidate)
    try:
        os.chmod(temp, mode)
        os.replace(temp, site)
        try:
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
        except Exception:
            site.write_text(old)
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
            raise
    finally:
        temp.unlink(missing_ok=True)


def _container(project: str, service: str) -> str:
    ids = _run("docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={project}",
               "--filter", f"label=com.docker.compose.service={service}").splitlines()
    if len(ids) != 1:
        raise RuntimeError(f"Expected one running {service} container, got {len(ids)}")
    return ids[0]


def _project_and_image() -> tuple[str, str]:
    ids = _run("docker", "ps", "-q", "--filter", "publish=8000").splitlines()
    if len(ids) != 1:
        raise RuntimeError("Expected one current MCP on port 8000")
    cid = ids[0]
    project = _run("docker", "inspect", "-f", '{{index .Config.Labels "com.docker.compose.project"}}', cid)
    service = _run("docker", "inspect", "-f", '{{index .Config.Labels "com.docker.compose.service"}}', cid)
    image = _run("docker", "inspect", "-f", "{{.Image}}", cid)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project) or service != "mcp" or not IMAGE_ID.fullmatch(image):
        raise RuntimeError("Current port 8000 is not a pinned Compose MCP container")
    return project, image


def _compose(path: Path, project: str, image: str, *args: str, timeout: int = 120) -> str:
    env = dict(os.environ, MCP_IMAGE=image, GIT_SHA=path.parent.name,
               UID=str(os.getuid() or 1000), GID=str(os.getgid() or 1000),
               REDIS_URL="redis://redis:6379/0", RATE_LIMIT_REQUIRE_REDIS="1",
               STREAMABLE_HTTP_DRAIN_ENABLED="1")
    return _run("docker", "compose", "--env-file", str(path.parent / ".env"),
                "-p", project, "-f", str(path), "--profile", "production", *args,
                cwd=path.parent, env=env, timeout=timeout)


def _ready(port: int, seconds: int = 90) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with opener.open(f"http://127.0.0.1:{port}/readyz", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(1)
    raise TimeoutError(f"slot {port} did not become ready")


def _stateless_protocol_ready(port: int) -> None:
    """Prove each new slot accepts discovery with and without an old session ID."""
    initialize = {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "deploy-preflight", "version": "1"},
    }
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for method, params in (("initialize", initialize), ("tools/list", {})):
        body = json.dumps({"jsonrpc": "2.0", "id": 1,
                           "method": method, "params": params}).encode()
        for headers in ({}, {"Mcp-Session-Id": "previous-worker-session"}):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp", data=body, method="POST",
                headers={"Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream", **headers},
            )
            try:
                with opener.open(request, timeout=10) as response:
                    raw = response.read(2_097_153).decode()
                    session_id = response.headers.get("mcp-session-id")
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                raise RuntimeError(f"slot {port} failed stateless MCP preflight") from exc
            if len(raw) > 2_097_152:
                raise RuntimeError(f"slot {port} MCP preflight body is too large")
            data = next((line[6:] for line in raw.splitlines() if line.startswith("data: ")), raw)
            try:
                payload = json.loads(data)
            except ValueError as exc:
                raise RuntimeError(f"slot {port} returned invalid MCP preflight body") from exc
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            valid = (result.get("protocolVersion") == "2025-03-26" if method == "initialize"
                     else isinstance(result.get("tools"), list))
            if session_id or not valid:
                raise RuntimeError(f"slot {port} is not stateless MCP")


def _nginx_local_smoke(hostname: str, *, port: int = 443, seconds: int = 10) -> None:
    """Check the selected TLS site through loopback, without external DNS."""
    if not re.fullmatch(r"[a-z0-9.-]+", hostname):
        raise ValueError("Invalid nginx hostname")
    # The certificate name cannot match a loopback URL; this checks local
    # proxy routing only. The separate public smoke checks TLS identity.
    class NoRedirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
        NoRedirects(),
    )
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            def fetch(path: str) -> tuple[int, bytes]:
                request = urllib.request.Request(f"https://127.0.0.1:{port}{path}",
                                                 headers={"Host": hostname})
                try:
                    with opener.open(request, timeout=2) as response:
                        return response.status, response.read(1024) if path == "/healthz" else b""
                except urllib.error.HTTPError as exc:
                    return exc.code, exc.read(1024)

            health_status, health_body = fetch("/healthz")
            mcp_status, _ = fetch("/mcp")
            if (health_status == 200 and json.loads(health_body).get("status") == "ok"
                    and (200 <= mcp_status < 300 or 400 <= mcp_status < 500)
                    and mcp_status != 404):
                return
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError):
            pass
        time.sleep(0.2)
    raise TimeoutError("local nginx healthz did not become ready")


def _backup_pg(project: str, bundle: Path) -> Path:
    cid = _container(project, "postgres")
    dest = bundle / "pre-deploy.dump"
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            result = subprocess.run(["docker", "exec", cid, "sh", "-c",
                                     'pg_dump -Fc --exclude-table-data=public.report_ai_job_ratings '
                                     '-U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
                                    stdout=handle, stderr=subprocess.PIPE, timeout=300)
        if result.returncode != 0 or dest.stat().st_size < 100:
            raise RuntimeError(f"PostgreSQL backup failed (exit {result.returncode})")
        with dest.open("rb") as handle:
            if handle.read(5) != b"PGDMP":
                raise RuntimeError("PostgreSQL backup has an invalid custom format header")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest


def _check_observability_secrets(env_file: Path) -> None:
    values = {}
    for line in env_file.read_text().splitlines():
        if line.startswith(("GRAFANA_ADMIN_PASSWORD=", "METRICS_AUTH_TOKEN=")):
            key, value = line.split("=", 1)
            values[key] = value.strip().strip('"\'')
    if values.get("GRAFANA_ADMIN_PASSWORD", "").lower() in {"", "admin", "password", "changeme"}:
        raise RuntimeError("GRAFANA_ADMIN_PASSWORD must be set to a non-default secret value")
    if not values.get("METRICS_AUTH_TOKEN"):
        raise RuntimeError("METRICS_AUTH_TOKEN must be set before production deploy")


def _save_pre385_source(live: Path, bundle: Path) -> None:
    """Freeze the bind-mounted old checkout without credentials or runtime data."""
    excluded_dirs = {".git", ".venv", "data", "logs", "releases", "release-state",
                     "__pycache__", ".pytest_cache", ".cursor", ".codex", ".claude"}
    output = bundle / "old-source.tar.gz"
    with tarfile.open(output, "x:gz") as archive:
        for root, dirs, files in os.walk(live, followlinks=False):
            dirs[:] = [name for name in dirs if name not in excluded_dirs]
            for name in files:
                if (name.startswith((".env", ".feedback_fingerprint_pepper"))
                        or name.endswith((".key", ".pem"))):
                    continue
                path = Path(root) / name
                if path.is_symlink() or not path.is_file():
                    continue
                archive.add(path, arcname=str(path.relative_to(live)), recursive=False)
    os.chmod(output, 0o400)


def _running_new_slots(project: str, image: str) -> tuple[str, ...]:
    """Find only new containers; an exited new slot leaves its writes unresolved."""
    running = []
    for service in SLOTS:
        ids = _run("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}",
                   "--filter", f"label=com.docker.compose.service={service}").splitlines()
        matched = [cid for cid in ids if _run("docker", "inspect", "-f", "{{.Image}}", cid) == image]
        if len(matched) > 1:
            raise RuntimeError(f"Multiple new {service} containers; reconcile writes")
        if matched:
            if _run("docker", "inspect", "-f", "{{.State.Running}}", matched[0]) != "true":
                raise RuntimeError(f"New {service} exited without proven drain; reconcile writes")
            running.append(service)
    return tuple(running)


def _stop_old(project: str, slots: tuple[str, ...], *, fence: bool = False) -> None:
    if len(slots) == 3 or fence:
        for service in slots:
            _run("docker", "kill", "--signal=USR1", _container(project, service))
        for service in slots:
            _wait_write_fence(SLOTS[service], seconds=60)
    for service in slots:
        cid = _container(project, service)
        since = datetime.now(timezone.utc).isoformat()
        _run("docker", "update", "--restart=no", cid)
        _run("docker", "kill", "--signal=TERM", cid)
        _run("docker", "wait", cid, timeout=50)
        exit_code = _run("docker", "inspect", "-f", "{{.State.ExitCode}}", cid)
        running = _run("docker", "inspect", "-f", "{{.State.Running}}", cid)
        logs = subprocess.run(["docker", "logs", "--since", since, cid],
                              check=True, capture_output=True, text=True)
        combined = logs.stdout + logs.stderr
        if (exit_code != "0" or running != "false" or not _drain_finished(combined)
                or "write_drain_timeout" in combined or "Cancel " in combined):
            raise RuntimeError(f"{service} did not prove graceful drain; reconcile writes before proceeding")


def deploy(release: Path, live: Path, sha: str, *, site: Path = SITE, pepper: str) -> None:
    if not SHA.fullmatch(sha) or release.name != sha or not (release / "docker-compose.yml").is_file():
        raise ValueError("Release directory/SHA mismatch")
    if not pepper or "\n" in pepper or "\r" in pepper:
        raise ValueError("Invalid fingerprint pepper")
    if not (live / ".env").is_file():
        raise RuntimeError("Live .env missing")
    _check_observability_secrets(live / ".env")
    project, old_image = _project_and_image()
    state_dir = live / "release-state"
    state_dir.mkdir(mode=0o700, exist_ok=True)
    state_file = state_dir / "current.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else None
    if state:
        base = (state_dir / "base-nginx.conf").read_text()
        previous = Path(state["release"])
        if not previous.is_relative_to(live / "releases") or not previous.is_dir():
            raise RuntimeError("Recorded previous release is unsafe")
        old_compose = previous / "docker-compose.yml"
        slots = tuple(SLOTS)
        if state["image"] != old_image:
            raise RuntimeError("Running image disagrees with release state")
        if site.read_text() != render_nginx_site(base, "active"):
            raise RuntimeError("Active nginx site disagrees with release state")
        for service in ("mcp2", "mcp3"):
            image = _run("docker", "inspect", "-f", "{{.Image}}", _container(project, service))
            if image != old_image:
                raise RuntimeError(f"{service} image disagrees with release state")
    else:
        base = site.read_text()
        old_compose = live / "docker-compose.yml"
        slots = ("mcp",)
    maintenance = render_nginx_site(base, "maintenance")
    active = render_nginx_site(base, "active")
    host_match = re.search(r"(?m)^\s*server_name\s+([a-z0-9.-]+);", base)
    if host_match is None:
        raise RuntimeError("Base nginx hostname is missing")
    hostname = host_match.group(1)
    # Persist the exact active nginx file and immutable rollback before any stop.
    bundle = state_dir / "rollback" / sha
    bundle.parent.mkdir(mode=0o700, exist_ok=True)
    bundle.mkdir(mode=0o700)
    (bundle / "nginx-before.conf").write_text(site.read_text())
    (bundle / "base-nginx.conf").write_text(base)
    (bundle / ".env").symlink_to(live / ".env")
    rollback_file = bundle / "rollback.yml"
    write_rollback_manifest(rollback_file,
                            make_rollback_manifest(yaml.safe_load(old_compose.read_text()),
                                                   old_image, project, slot_count=len(slots)))
    _compose(rollback_file, project, old_image, "config", "--quiet")
    (bundle / "metadata.json").write_text(json.dumps({"old_image": old_image,
        "project": project, "old_slots": slots, "old_release": str(old_compose.parent)}, indent=2))
    if not state:
        _save_pre385_source(live, bundle)
    (release / ".env").symlink_to(live / ".env")
    with tempfile.NamedTemporaryFile("w", dir=state_dir, prefix=".pepper-", delete=False) as handle:
        secret = Path(handle.name)
        handle.write(pepper)
    try:
        os.chmod(secret, 0o600)
        update_env_secret(live / ".env", "FEEDBACK_FINGERPRINT_PEPPER", secret)
    finally:
        secret.unlink(missing_ok=True)
    _backup_pg(project, bundle)
    _run("docker", "tag", old_image, f"vetmanager-mcp:rollback-{sha}")
    _run("docker", "build", "--target", "production", "--build-arg", f"UID={os.getuid() or 1000}",
         "--build-arg", f"GID={os.getgid() or 1000}", "--build-arg", f"ERROR_TRACKING_RELEASE={sha}",
         "-t", f"vetmanager-mcp:{sha}", ".", cwd=release, timeout=900)
    new_image = _run("docker", "image", "inspect", "-f", "{{.Id}}", f"vetmanager-mcp:{sha}")
    if not IMAGE_ID.fullmatch(new_image):
        raise RuntimeError("Built image is not pinned")
    _compose(release / "docker-compose.yml", project, new_image, "config", "--quiet")
    resolved = json.loads(_compose(release / "docker-compose.yml", project, new_image,
                                   "config", "--format", "json"))
    metrics_token = resolved["services"]["mcp"]["environment"].get("METRICS_AUTH_TOKEN")
    if not metrics_token:
        raise RuntimeError("MCP metrics token did not reach the new Compose service")
    maintenance_entered = False
    old_stopped = False
    new_launch_attempted = False
    try:
        _write_site(maintenance, site)
        maintenance_entered = True
        _stop_old(project, slots)
        old_stopped = True
        _compose(release / "docker-compose.yml", project, new_image, "up", "-d", "redis")
        _compose(release / "docker-compose.yml", project, new_image, "run", "-T", "--rm", "mcp",
                 "alembic", "upgrade", "head", timeout=300)
        new_launch_attempted = True
        _compose(release / "docker-compose.yml", project, new_image, "up", "-d", "--no-build",
                 "--force-recreate", *SLOTS, timeout=300)
        for port in SLOTS.values():
            _ready(port)
            _stateless_protocol_ready(port)
        _write_site(active, site)
        _nginx_local_smoke(hostname)
        _run("bash", "scripts/post_deploy_smoke_checks.sh", "http://127.0.0.1:8000",
             cwd=release, env=dict(os.environ, METRICS_AUTH_TOKEN=metrics_token),
             timeout=180)
        if not state:
            (state_dir / "base-nginx.conf").write_text(base)
        state_file.write_text(json.dumps({"release": str(release), "image": new_image}, indent=2))
        try:
            _compose(release / "docker-compose.yml", project, new_image, "up", "-d",
                     "--no-build", "prometheus", "grafana", timeout=180)
        except Exception as exc:
            print(f"observability restart failed after app cutover: {exc}", file=sys.stderr)
        print(f"cutover complete: {sha}; slots=3; rollback={rollback_file}")
    except Exception:
        if maintenance_entered and old_stopped:
            try:
                _write_site(maintenance, site)
                # Once a slot could have served a write, rollback needs the
                # same fleet fence and proven graceful drain as forward cutover.
                # A partial or unknown new fleet keeps maintenance in place.
                if new_launch_attempted:
                    new_slots = _running_new_slots(project, new_image)
                    if new_slots:
                        _stop_old(project, new_slots, fence=True)
                _compose(rollback_file, project, old_image, "up", "-d", "--no-build",
                         "--force-recreate", *slots, timeout=300)
                for service in slots:
                    _ready(SLOTS[service])
                _write_site((bundle / "nginx-before.conf").read_text(), site)
                print(f"rolled back to exact image {old_image}", file=sys.stderr)
            except Exception as rollback_error:
                print(f"rollback failed; maintenance retained: {rollback_error}", file=sys.stderr)
                _write_site(maintenance, site)
        elif maintenance_entered:
            # A write outcome may be unknown. Keep maintenance until reconciled.
            print("old write outcome may be unknown; maintenance retained", file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("release", type=Path)
    parser.add_argument("live", type=Path)
    parser.add_argument("sha")
    args = parser.parse_args()
    deploy(args.release.resolve(), args.live.resolve(), args.sha, pepper=sys.stdin.read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

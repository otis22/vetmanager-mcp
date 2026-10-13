#!/usr/bin/env python3
"""Quiesce one compatible MCP slot before an operator replaces its image.

The first migration from the single pre-385 process uses fleet maintenance,
not this rolling procedure.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


SLOTS = {"mcp": 8000, "mcp2": 8001, "mcp3": 8002}
UPSTREAM = re.compile(r"(upstream (mcp_backend|mcp_session_backend) \{\n)(.*?)(\n\})", re.S)
SERVER = re.compile(r"^    server 127\.0\.0\.1:(\d+)( down)?;$", re.M)


def remove_backend_from_site(source: str, port: int) -> str:
    matches = {match.group(2): match for match in UPSTREAM.finditer(source)}
    sticky = matches.get("mcp_session_backend")
    web = matches.get("mcp_backend")
    if sticky is None or "hash " not in sticky.group(3) or "http_authorization consistent;" not in sticky.group(3):
        raise ValueError("nginx sticky upstream is missing")
    if web is None:
        raise ValueError("nginx web backend is missing")
    replacements = []
    for name, match in (("mcp_backend", web), ("mcp_session_backend", sticky)):
        body = match.group(3)
        servers = [(int(p), down) for p, down in SERVER.findall(body)]
        if port not in [p for p, _ in servers]:
            raise ValueError(f"slot is not in nginx {name}")
        if not any(p != port and not down for p, down in servers):
            label = "web backend" if name == "mcp_backend" else "last nginx slot"
            raise ValueError(f"cannot remove {label}; enter fleet maintenance")
        updated_body = re.sub(rf"(?m)^    server 127\.0\.0\.1:{port}(?: down)?;\n", "", body, count=1)
        replacements.append((match.start(3), match.end(3), updated_body))
    for start, end, body in sorted(replacements, reverse=True):
        source = source[:start] + body + source[end:]
    return source


def _drain_finished(logs: str) -> bool:
    return ("event_name=streamable_http_drain_finished" in logs
            or bool(re.search(r'"event_name"\s*:\s*"streamable_http_drain_finished"', logs)))


def _run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def _write_atomic(path: Path, value: str) -> None:
    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".mcp-nginx-", delete=False) as handle:
        temp = Path(handle.name)
        handle.write(value)
    try:
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _wait_write_fence(port: int, *, seconds: float) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            response = opener.open(f"http://127.0.0.1:{port}/readyz", timeout=2)
        except urllib.error.HTTPError as exc:
            response = exc
        except (urllib.error.URLError, TimeoutError):
            time.sleep(.25)
            continue
        try:
            body = json.load(response)
        except (ValueError, UnicodeDecodeError):
            body = {}
        if response.status == 503 and body.get("in_flight_writes") == 0:
            return
        time.sleep(.25)
    raise TimeoutError("write fence did not reach zero; slot remains in nginx")


def _wait_sse_close(cid: str, since: str, *, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        logs = subprocess.run(
            ["docker", "logs", "--since", since, cid], capture_output=True, text=True, check=True,
        )
        if _drain_finished(logs.stdout + logs.stderr):
            return
        time.sleep(.25)
    raise TimeoutError("SSE close was not observed; slot remains in nginx")


def quiesce_slot(service: str, site: Path, *, project_name: str,
                 grace_seconds: float = 5, timeout_seconds: float = 60) -> None:
    port = SLOTS[service]
    original = site.read_text()
    updated = remove_backend_from_site(original, port)
    cid = _run("docker", "compose", "-p", project_name,
               "--profile", "production", "ps", "-q", service)
    if not cid:
        raise RuntimeError("slot container is missing")
    _run("docker", "kill", "--signal=USR1", cid)
    try:
        _wait_write_fence(port, seconds=timeout_seconds)
    except TimeoutError as exc:
        # A timed-out write may still be running. Stop new traffic, but do not
        # terminate or restart its process before the outcome is reconciled.
        _write_atomic(site, updated)
        try:
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
        except Exception:
            _write_atomic(site, original)
            raise RuntimeError("write fence timed out and nginx route removal failed; operator recovery required") from exc
        raise TimeoutError("write fence timed out; route removed, worker still running for reconciliation") from exc
    time.sleep(grace_seconds)
    since = datetime.now(timezone.utc).isoformat()
    _run("docker", "kill", "--signal=USR2", cid)
    try:
        _wait_sse_close(cid, since, seconds=timeout_seconds)
    except (TimeoutError, subprocess.CalledProcessError) as exc:
        # The write fence is complete. Remove new traffic but retain this
        # process until the operator can establish the SSE outcome.
        _write_atomic(site, updated)
        try:
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
        except Exception:
            _write_atomic(site, original)
            _run("nginx", "-t")
            _run("systemctl", "reload", "nginx")
            _run("docker", "compose", "-p", project_name, "--profile", "production", "restart", service)
            raise RuntimeError("SSE close unknown and nginx route removal failed") from exc
        raise TimeoutError("SSE close unknown; route removed, worker still running") from exc
    _write_atomic(site, updated)
    try:
        _run("nginx", "-t")
        _run("systemctl", "reload", "nginx")
    except Exception:
        _write_atomic(site, original)
        _run("nginx", "-t")
        _run("systemctl", "reload", "nginx")
        _run("docker", "compose", "-p", project_name, "--profile", "production", "restart", service)
        raise
    _run("docker", "stop", "--time", "30", cid)
    print(f"slot {service} quiesced, removed from nginx, and stopped")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=sorted(SLOTS))
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--grace-seconds", type=float, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=60)
    args = parser.parse_args()
    if args.grace_seconds < 0 or args.timeout_seconds <= 0:
        parser.error("grace must be nonnegative and timeout must be positive")
    quiesce_slot(args.service, args.site, project_name=args.project_name,
                 grace_seconds=args.grace_seconds,
                 timeout_seconds=args.timeout_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

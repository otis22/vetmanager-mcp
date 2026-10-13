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
UPSTREAM = re.compile(r"(upstream mcp_session_backend \{\n)(.*?)(\n\})", re.S)
SERVER = re.compile(r"^    server 127\.0\.0\.1:(\d+);$", re.M)


def remove_backend_from_site(source: str, port: int) -> str:
    match = UPSTREAM.search(source)
    if match is None or "hash " not in match.group(2) or "http_authorization consistent;" not in match.group(2):
        raise ValueError("nginx sticky upstream is missing")
    body = match.group(2)
    ports = [int(value) for value in SERVER.findall(body)]
    if port not in ports:
        raise ValueError("slot is not in nginx upstream")
    if len(ports) <= 1:
        raise ValueError("cannot remove the last nginx slot; enter fleet maintenance")
    updated_body = re.sub(rf"(?m)^    server 127\.0\.0\.1:{port};\n", "", body, count=1)
    return source[:match.start(2)] + updated_body + source[match.end(2):]


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
        if "event_name=streamable_http_drain_finished" in logs.stdout + logs.stderr:
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
    _wait_write_fence(port, seconds=timeout_seconds)
    time.sleep(grace_seconds)
    since = datetime.now(timezone.utc).isoformat()
    _run("docker", "kill", "--signal=USR2", cid)
    _wait_sse_close(cid, since, seconds=timeout_seconds)
    _write_atomic(site, updated)
    try:
        _run("nginx", "-t")
        _run("systemctl", "reload", "nginx")
    except Exception:
        _write_atomic(site, original)
        _run("nginx", "-t")
        _run("systemctl", "reload", "nginx")
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

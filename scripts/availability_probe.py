#!/usr/bin/env python3
"""Bounded, authenticated availability probe for fixed worker and proxy routes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

SLOTS = ("mcp", "mcp2", "mcp3")
TIMEOUT_SECONDS = 4.0
MAX_HEALTH_BYTES = 65536


def _service_health_url(base: str) -> str:
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or parsed.port not in (None, 443)):
        raise ValueError("SITE_BASE_URL must be an HTTPS origin")
    return base.rstrip("/") + "/healthz"


def _fetch_json(url: str, timeout: float) -> tuple[int, dict] | None:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_HEALTH_BYTES + 1)
            if len(payload) > MAX_HEALTH_BYTES:
                return None  # An oversized response cannot establish target state.
            return response.status, json.loads(payload)
    except HTTPError as exc:
        return exc.code, {}
    except (URLError, TimeoutError, OSError):
        return None  # A transport failure does not identify a failed target.
    except (ValueError, json.JSONDecodeError):
        return 200, {}  # Reachable target returned an invalid health response.


def collect(base_url: str, token: str, authorization: str | None) -> str | None:
    """Return only fixed, non-identifying metrics; None means authorization failed."""
    if not token or not hmac.compare_digest(authorization or "", "Bearer " + token):
        return None
    service_url = _service_health_url(base_url)
    targets = [(slot, f"http://{slot}:8000/readyz") for slot in SLOTS]
    targets.append(("service", service_url))
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda item: _fetch_json(item[1], TIMEOUT_SECONDS), targets))
    lines = ["# HELP vetmanager_worker_ready Worker readiness through independent probe.",
             "# TYPE vetmanager_worker_ready gauge",
             "# HELP vetmanager_service_healthz Nginx health route status.",
             "# TYPE vetmanager_service_healthz gauge",
             "# HELP vetmanager_probe_unknown Probe could not classify target state.",
             "# TYPE vetmanager_probe_unknown gauge"]
    unknown = []
    for (slot, _), result in zip(targets[:3], responses[:3]):
        if result is None:
            unknown.append(slot)
            continue
        code, body = result
        ready = int(code == 200 and body.get("status") == "ok"
                    and body.get("probe") == "readiness")
        lines.append(f'vetmanager_worker_ready{{slot="{slot}"}} {ready}')
    if responses[3] is None:
        unknown.append("service")
    else:
        code, body = responses[3]
        route_ok = int(code == 200 and body.get("status") == "ok"
                       and body.get("probe") == "liveness")
        lines.append(f"vetmanager_service_healthz {route_ok}")
    lines.extend(f'vetmanager_probe_unknown{{slot="{slot}"}} 1' for slot in unknown)
    return "\n".join(lines) + "\n"


def main() -> None:
    base = os.environ["SITE_BASE_URL"]
    token = os.environ["METRICS_AUTH_TOKEN"]
    _service_health_url(base)
    if not token:
        raise RuntimeError("METRICS_AUTH_TOKEN is required")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/probe-metrics":
                self.send_error(404)
                return
            body = collect(base, token, self.headers.get("Authorization"))
            if body is None:
                self.send_error(403)
                return
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args: object) -> None:
            pass

    ThreadingHTTPServer(("0.0.0.0", 8003), Handler).serve_forever()


if __name__ == "__main__":
    main()

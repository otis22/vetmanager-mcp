import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "post_deploy_smoke_checks.sh"


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _HealthyHandler(BaseHTTPRequestHandler):
    expected_metrics_token: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/readyz":
            body = b'{"status":"ready"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/metrics":
            if (
                self.expected_metrics_token is not None
                and self.headers.get("Authorization")
                != f"Bearer {self.expected_metrics_token}"
            ):
                self.send_response(403)
                self.end_headers()
                return
            body = b"# HELP vetmanager_http_requests_total\nvetmanager_http_requests_total 1\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/mcp":
            self.send_response(405)
            self.end_headers()
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _run_smoke_script(base_url: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), base_url],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )


def test_post_deploy_smoke_checks_retries_until_service_is_ready() -> None:
    port = _get_free_port()
    server_holder: dict[str, ThreadingHTTPServer] = {}

    def start_server_later() -> None:
        time.sleep(0.5)
        httpd = ThreadingHTTPServer(("127.0.0.1", port), _HealthyHandler)
        server_holder["httpd"] = httpd
        httpd.serve_forever()

    thread = threading.Thread(target=start_server_later, daemon=True)
    thread.start()

    try:
        result = _run_smoke_script(
            f"http://127.0.0.1:{port}",
            SMOKE_MAX_ATTEMPTS="10",
            SMOKE_SLEEP_SECONDS="0.1",
            SMOKE_REQUEST_MAX_TIME_SECONDS="1",
        )
    finally:
        httpd = server_holder.get("httpd")
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Post-deploy smoke checks passed." in result.stdout


def test_post_deploy_smoke_checks_fail_with_attempt_context() -> None:
    port = _get_free_port()
    result = _run_smoke_script(
        f"http://127.0.0.1:{port}",
        SMOKE_MAX_ATTEMPTS="2",
        SMOKE_SLEEP_SECONDS="0.1",
        SMOKE_REQUEST_MAX_TIME_SECONDS="1",
    )

    combined_output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "healthz failed after 2 attempts" in combined_output
    assert f"http://127.0.0.1:{port}/healthz" in combined_output
    assert "request_exit=" in combined_output


def test_post_deploy_smoke_checks_sends_metrics_bearer_token() -> None:
    port = _get_free_port()
    _HealthyHandler.expected_metrics_token = "secret-metrics-token"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _HealthyHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        result = _run_smoke_script(
            f"http://127.0.0.1:{port}",
            METRICS_AUTH_TOKEN="secret-metrics-token",
            SMOKE_MAX_ATTEMPTS="2",
            SMOKE_SLEEP_SECONDS="0.1",
            SMOKE_REQUEST_MAX_TIME_SECONDS="1",
        )
    finally:
        _HealthyHandler.expected_metrics_token = None
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0, result.stdout + result.stderr


def test_post_deploy_smoke_checks_fails_when_metrics_token_rejected() -> None:
    port = _get_free_port()
    _HealthyHandler.expected_metrics_token = "expected-token"
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _HealthyHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        result = _run_smoke_script(
            f"http://127.0.0.1:{port}",
            METRICS_AUTH_TOKEN="wrong-token",
            SMOKE_MAX_ATTEMPTS="1",
            SMOKE_SLEEP_SECONDS="0.1",
            SMOKE_REQUEST_MAX_TIME_SECONDS="1",
        )
    finally:
        _HealthyHandler.expected_metrics_token = None
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)

    combined_output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "metrics failed after 1 attempts" in combined_output
    assert "http_status=403" in combined_output


class _RedirectingHandler(_HealthyHandler):
    """/healthz answers 302 towards a page that is perfectly healthy."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self.send_response(302)
            self.send_header("Location", "/healthz-ok")
            self.end_headers()
            return
        if self.path == "/healthz-ok":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


class _DribblingHandler(_HealthyHandler):
    """Answers /healthz correctly, one byte at a time, forever slowly."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body) + 200))
            self.end_headers()
            for chunk in body:
                self.wfile.write(bytes([chunk]))
                self.wfile.flush()
                time.sleep(0.6)
            return
        super().do_GET()


def _serve(handler_class, port: int):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler_class)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread


def test_a_redirect_is_an_answer_not_a_step_towards_one() -> None:
    """Stage 267: curl ran without -L, so a 3xx failed the check.

    A redirect that lands on a healthy page would otherwise hide a broken route.
    """
    port = _get_free_port()
    httpd, thread = _serve(_RedirectingHandler, port)
    try:
        result = _run_smoke_script(
            f"http://127.0.0.1:{port}",
            SMOKE_MAX_ATTEMPTS="2",
            SMOKE_SLEEP_SECONDS="0.1",
            SMOKE_REQUEST_MAX_TIME_SECONDS="2",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "http_status=302" in combined
    # Refusing the redirect is only half the job: say where it pointed.
    assert "/healthz-ok" in combined, combined


def test_a_slow_dribble_hits_the_deadline_for_the_whole_request() -> None:
    """Stage 267: `urlopen(timeout=)` bounds one socket read, not the transfer.

    Measured before the fix: a body sent one byte per 0.6s passed a one-second
    limit after ten seconds, because every single read was fast enough.
    """
    port = _get_free_port()
    httpd, thread = _serve(_DribblingHandler, port)
    started = time.monotonic()
    try:
        result = _run_smoke_script(
            f"http://127.0.0.1:{port}",
            SMOKE_MAX_ATTEMPTS="1",
            SMOKE_SLEEP_SECONDS="0.1",
            SMOKE_REQUEST_MAX_TIME_SECONDS="1",
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
    elapsed = time.monotonic() - started

    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert elapsed < 8, f"the deadline did not bound the transfer: {elapsed:.1f}s"
    # curl aborted the transfer and still printed the status it already had.
    # Dropping it would make a dribbling peer look like an unreachable one.
    assert "http_status=200" in combined, combined

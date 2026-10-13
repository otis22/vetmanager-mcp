"""Removing a worker from nginx must preserve a valid sticky upstream."""

from pathlib import Path

import pytest

from scripts import quiesce_mcp_slot
from scripts.quiesce_mcp_slot import remove_backend_from_site


SITE = (Path(__file__).resolve().parents[1] / "scripts/init_server.sh").read_text().replace(
    "server 127.0.0.1:8001 down;", "server 127.0.0.1:8001;"
).replace("server 127.0.0.1:8002 down;", "server 127.0.0.1:8002;")


def test_remove_one_slot_from_both_upstreams():
    updated = remove_backend_from_site(SITE, 8001)
    sticky = updated.split("upstream mcp_session_backend {", 1)[1].split("}", 1)[0]
    assert "server 127.0.0.1:8001;" not in sticky
    assert "server 127.0.0.1:8000;" in sticky
    assert "server 127.0.0.1:8002;" in sticky
    assert "hash \\$http_authorization consistent;" in sticky
    assert "server 127.0.0.1:8001;" not in updated.split("upstream mcp_backend {", 1)[1].split("}", 1)[0]
    assert "upstream mcp_backend {\n    server 127.0.0.1:8000;" in updated


def test_cannot_remove_only_active_web_slot():
    original = (Path(__file__).resolve().parents[1] / "scripts/init_server.sh").read_text()
    with pytest.raises(ValueError, match="web backend"):
        remove_backend_from_site(original, 8000)


def test_json_drain_event_is_recognized():
    assert quiesce_mcp_slot._drain_finished('{"event_name": "streamable_http_drain_finished"}')


def test_cannot_remove_final_slot():
    one_slot = remove_backend_from_site(remove_backend_from_site(SITE, 8001), 8002)
    with pytest.raises(ValueError, match="web backend|last"):
        remove_backend_from_site(one_slot, 8000)


def test_invalid_nginx_config_restores_site_without_stopping_worker(tmp_path, monkeypatch):
    site = tmp_path / "site.conf"
    site.write_text(SITE)
    calls = []

    def fake_run(*args):
        calls.append(args)
        if args[:3] == ("docker", "compose", "-p"):
            return "test-container"
        if args == ("nginx", "-t") and calls.count(("nginx", "-t")) == 1:
            raise RuntimeError("nginx config invalid")
        return ""

    monkeypatch.setattr(quiesce_mcp_slot, "_run", fake_run)
    monkeypatch.setattr(quiesce_mcp_slot, "_wait_write_fence", lambda *a, **k: calls.append(("fence",)))
    monkeypatch.setattr(quiesce_mcp_slot, "_wait_sse_close", lambda *a, **k: calls.append(("sse",)))
    monkeypatch.setattr(quiesce_mcp_slot.time, "sleep", lambda *_: None)
    with pytest.raises(RuntimeError, match="nginx config invalid"):
        quiesce_mcp_slot.quiesce_slot("mcp2", site, project_name="stage385probe", grace_seconds=0)
    assert site.read_text() == SITE
    assert calls.index(("fence",)) < calls.index(("sse",)) < calls.index(("nginx", "-t"))
    assert ("docker", "stop", "--time", "30", "test-container") not in calls
    assert ("docker", "compose", "-p", "stage385probe", "--profile", "production", "restart", "mcp2") in calls
    assert any(call[:5] == ("docker", "compose", "-p", "stage385probe", "--profile") for call in calls)


def test_fence_timeout_detaches_route_but_keeps_worker(tmp_path, monkeypatch):
    site = tmp_path / "site.conf"
    site.write_text(SITE)
    calls = []

    def fake_run(*args):
        calls.append(args)
        return "test-container" if args[:3] == ("docker", "compose", "-p") else ""

    def timeout(*_args, **_kwargs):
        raise TimeoutError("write fence did not reach zero")

    monkeypatch.setattr(quiesce_mcp_slot, "_run", fake_run)
    monkeypatch.setattr(quiesce_mcp_slot, "_wait_write_fence", timeout)
    with pytest.raises(TimeoutError, match="route removed"):
        quiesce_mcp_slot.quiesce_slot("mcp2", site, project_name="stage385probe", grace_seconds=0)
    assert "server 127.0.0.1:8001;" not in site.read_text()
    assert ("systemctl", "reload", "nginx") in calls
    assert ("docker", "stop", "--time", "30", "test-container") not in calls


def test_sse_log_timeout_detaches_fenced_route(tmp_path, monkeypatch):
    site = tmp_path / "site.conf"
    site.write_text(SITE)
    calls = []

    def fake_run(*args):
        calls.append(args)
        return "test-container" if args[:3] == ("docker", "compose", "-p") else ""

    def timeout(*_args, **_kwargs):
        raise TimeoutError("SSE close was not observed")

    monkeypatch.setattr(quiesce_mcp_slot, "_run", fake_run)
    monkeypatch.setattr(quiesce_mcp_slot, "_wait_write_fence", lambda *a, **k: None)
    monkeypatch.setattr(quiesce_mcp_slot, "_wait_sse_close", timeout)
    monkeypatch.setattr(quiesce_mcp_slot.time, "sleep", lambda *_: None)
    with pytest.raises(TimeoutError, match="route removed"):
        quiesce_mcp_slot.quiesce_slot("mcp2", site, project_name="stage385probe", grace_seconds=0)
    assert "server 127.0.0.1:8001;" not in site.read_text()
    assert ("systemctl", "reload", "nginx") in calls
    assert ("docker", "stop", "--time", "30", "test-container") not in calls

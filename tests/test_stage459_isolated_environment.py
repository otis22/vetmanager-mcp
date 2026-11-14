"""Fail-closed container ownership and cleanup regression checks."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from scripts.test_recovery_supervisor import owned_container


def test_default_container_does_not_delay_every_http_fixture_reset():
    base = yaml.safe_load(Path("docker-compose.yml").read_text())["services"]["test"]
    isolated = yaml.safe_load(Path("docker-compose.test.yml").read_text())["services"]["test"]
    environment = {**base["environment"], **isolated["environment"]}
    assert environment.get("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS") in (None, "0", 0)


@pytest.mark.parametrize("labels", [
    {},
    {"com.docker.compose.project": "other", "com.docker.compose.service": "pg"},
    {"com.docker.compose.project": "ours", "com.docker.compose.service": "production"},
])
def test_refuses_foreign_container_before_mutation(monkeypatch, labels):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps([
        {"Id": "exact-id", "Config": {"Labels": labels}}
    ])))
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="outside this test project"):
        owned_container("candidate", "ours")
    assert run.call_args.args[0] == ["docker", "inspect", "candidate"]
    assert run.call_count == 1


def test_rejects_missing_container_without_docker_call(monkeypatch):
    run = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Missing"):
        owned_container("", "ours")
    run.assert_not_called()


def test_uses_inspected_exact_id(monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps([
        {"Id": "exact-id", "Config": {"Labels": {
            "com.docker.compose.project": "ours", "com.docker.compose.service": "pg"}}}
    ])))
    monkeypatch.setattr(subprocess, "run", run)
    assert owned_container("short-id", "ours") == "exact-id"


@pytest.mark.asyncio
@pytest.mark.parametrize("requirement", ["require_all", "require_api"])
async def test_complete_real_contour_is_required_before_token_exchange(tmp_path, monkeypatch, requirement):
    import scripts.prepare_real_test_auth as auth
    for key in ("TEST_DOMAIN", "TEST_API_KEY", "TEST_USER_LOGIN", "TEST_USER_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    exchange = Mock()
    monkeypatch.setattr(auth, "exchange_user_token", exchange)
    with pytest.raises(ValueError, match="Incomplete real test contour"):
        await auth.prepare(tmp_path / "auth.env", **{requirement: True})
    exchange.assert_not_called()
    assert not (tmp_path / "auth.env").exists()

"""Stage 113b: breaker/pool concurrency hardening regressions."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
import respx
from weakref import WeakKeyDictionary

from exceptions import VetmanagerError, VetmanagerUpstreamUnavailable
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient, get_breaker_state


DOMAIN = "stage113b-clinic"
API_KEY = "stage113b-key"
BASE = f"https://{DOMAIN}.vetmanager.cloud"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def _bearer_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="stage113b-token",
        bearer_token_id=1,
        connection_id=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_retryable_503_counts_toward_breaker_per_attempt(monkeypatch):
    """Stage 113b.2: sustained 503s should trip the breaker by attempt count,
    not by logical-call count.

    With threshold=2, one GET that sees two retryable 503 responses should
    already open the breaker. Under stage 105 semantics (one failure per
    logical call) the breaker would still be closed after this call.
    """
    monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "2")
    monkeypatch.setattr("vm_transport.retry.random.uniform", lambda a, b: 0.0)

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _no_sleep)

    _billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(503, json={"error": "degraded"})
    )

    headers_patch, runtime_patch = _bearer_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerUpstreamUnavailable):
            await VetmanagerClient().get("/rest/api/client", params={"limit": 1})

    state = get_breaker_state(DOMAIN)
    assert state is not None, "breaker state should exist after retryable 503s"
    assert state["state"] == "open", (
        f"breaker should open after two retryable 503 attempts, got {state}"
    )
    assert route.call_count == 2, (
        "threshold=2 should open breaker during the first logical GET call"
    )


@pytest.mark.asyncio
@respx.mock
async def test_retryable_429_does_not_count_toward_breaker(monkeypatch):
    """Stage 113b.2: HTTP 429 is rate limiting, not upstream health.

    Even if GET retries exhaust on 429, the circuit breaker must remain closed.
    """
    monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "2")
    monkeypatch.setattr("vm_transport.retry.random.uniform", lambda a, b: 0.0)

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _no_sleep)

    _billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(429, json={"error": "slow down"})
    )

    headers_patch, runtime_patch = _bearer_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerError):
            await VetmanagerClient().get("/rest/api/client", params={"limit": 1})

    state = get_breaker_state(DOMAIN)
    assert state is not None, "breaker state should exist after first admission"
    assert state["state"] == "closed", (
        f"429 retries must not open breaker; got {state}"
    )
    assert state["consecutive_failures"] == 0, (
        f"429 retries must not increment breaker failure count; got {state}"
    )
    assert route.call_count >= 2, "GET should still retry on 429"


def test_pool_and_host_resolver_registries_use_weak_keys():
    """Stage 113b.3: per-loop registries must auto-evict closed loops."""
    import host_resolver
    import vm_transport.pool

    assert isinstance(vm_transport.pool._shared_http_clients, WeakKeyDictionary)
    assert isinstance(host_resolver._shared_clients_by_loop, WeakKeyDictionary)
    assert isinstance(host_resolver._shared_clients_locks, WeakKeyDictionary)


def test_pool_and_host_resolver_have_no_import_time_asyncio_lock_assignments():
    """Stage 113b.4: avoid loop-bound `asyncio.Lock()` at import time."""
    files = [
        REPO_ROOT / "vm_transport" / "pool.py",
        REPO_ROOT / "host_resolver.py",
    ]
    offenders: list[str] = []

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            func = value.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "asyncio"
                and func.attr == "Lock"
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, (
        "loop-bound asyncio.Lock() must not be constructed at import time; "
        f"found {offenders}"
    )

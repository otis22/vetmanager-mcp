"""Stage 153 — Review-followup hardening (Kimi 2026-04-30).

Targeted regression tests for 6 fixes:
- F1: deploy_server.sh whitelist .env extract (no eval)
- F4/F5: atomic report_count increment via SQL UPDATE
- F13: collection-aware contains_any/contains_all
- F14: build_error_fingerprint_hash uses explicit `is not None`
- F15: /readyz wraps storage check in asyncio.wait_for
- F23: deploy-prod.yml deploy step has timeout-minutes
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

import agent_feedback_service as feedback
from fastmcp.exceptions import ToolError
from server import mcp
from storage_models import AgentFeedbackReport, KnownIssue
from tests.runtime_factories import make_runtime_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── F1: deploy_server.sh whitelist .env extract ─────────────────────────────


@pytest.mark.parametrize(
    "script_name",
    ["deploy_server.sh", "backup_daily_cron.sh", "rollback_db.sh"],
)
def test_f1_deploy_scripts_do_not_eval_env_file(script_name: str) -> None:
    script_text = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
    assert 'eval "$(grep' not in script_text, (
        f"F1: eval-based .env source in {script_name} must be replaced with whitelist extract"
    )
    assert 'eval "$(' not in script_text, (
        f"F1: no eval-based command substitution allowed in {script_name}"
    )


def test_f1_deploy_server_whitelist_extracts_only_postgres_keys(tmp_path: Path) -> None:
    """Synthetic test: extract POSTGRES_USER/DB from a metachar-laden .env, prove malicious values do not execute."""
    env_path = tmp_path / ".env"
    canary = tmp_path / "PWNED"
    env_path.write_text(
        "# header comment\n"
        "POSTGRES_USER=safeuser\n"
        f'MALICIOUS=$(touch "{canary}")\n'
        'POSTGRES_DB="quoteddb"\n'
        "OTHER_KEY=ignored_value\n"
        "DATABASE_URL=postgres://u:p@h/db?sslmode=require\n",
        encoding="utf-8",
    )

    script_text = (REPO_ROOT / "scripts" / "deploy_server.sh").read_text(encoding="utf-8")
    start = script_text.find("# Stage 153 (F1): whitelist-extract")
    end = script_text.find("# ── Build image once")
    assert start != -1 and end != -1, "Could not isolate .env source block in deploy_server.sh"
    env_block = script_text[start:end]

    bash_script = (
        f'cd "$1"\n'
        f'POSTGRES_USER=defaultuser\n'
        f'POSTGRES_DB=defaultdb\n'
        f'{env_block}\n'
        f'printf "USER=%s\\nDB=%s\\n" "$POSTGRES_USER" "$POSTGRES_DB"\n'
        f'if [ -n "${{MALICIOUS:-}}" ]; then echo "MALICIOUS_SOURCED=$MALICIOUS"; else echo "MALICIOUS_NOT_SOURCED"; fi\n'
        f'if [ -n "${{OTHER_KEY:-}}" ]; then echo "OTHER_SOURCED=$OTHER_KEY"; else echo "OTHER_NOT_SOURCED"; fi\n'
    )
    result = subprocess.run(
        ["bash", "-c", bash_script, "_", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
    )

    out = result.stdout
    assert "USER=safeuser" in out
    assert "DB=quoteddb" in out
    assert "MALICIOUS_NOT_SOURCED" in out, "F1: malicious key must NOT be sourced (whitelist only)"
    assert "OTHER_NOT_SOURCED" in out, "F1: non-whitelisted keys must NOT leak into env"
    assert not canary.exists(), "F1 CRITICAL: $(touch ...) inside .env value MUST NOT execute"


# ─── F4/F5: atomic report_count via UPDATE ────────────────────────────────────


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage153-test-pepper")


@pytest.mark.asyncio
async def test_f4_create_feedback_report_increments_known_issue_via_sql_update(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
) -> None:
    """Two sequential create_feedback_report calls must produce report_count=2 (UPDATE codepath)."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "f4.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        http_status=422,
        error_code="ToolError",
        error_excerpt="HTTP 422 date filter mismatch",
    )
    fingerprint = feedback.build_error_fingerprint_hash(incident)
    playbook = {
        "version": 1,
        "summary": "Use date filters.",
        "steps": ["Retry with date_from and date_to."],
        "do_not_do": [],
        "recommended_tool_sequence": ["get_payments"],
        "safe_to_retry": True,
    }
    rules = {
        "version": 1,
        "all": [
            {"field": "related_tool", "op": "eq", "value": "get_payments"},
            {"field": "http_status", "op": "eq", "value": 422},
        ],
    }
    async with session_factory() as session:
        session.add(KnownIssue(
            status="workaround_available",
            category="bug",
            severity="medium",
            title="Date filter required",
            related_tool="get_payments",
            error_fingerprint_hash=fingerprint,
            match_rules_json=json.dumps(rules),
            agent_playbook_json=json.dumps(playbook),
        ))
        await session.commit()

    for _ in range(2):
        await feedback.create_feedback_report(
            credentials=credentials,
            category="bug",
            severity="medium",
            summary="HTTP 422 from get_payments",
            details="HTTP 422 for date filter mismatch on payments tool",
            related_tool="get_payments",
            http_status=422,
            error_code="ToolError",
            error_excerpt="HTTP 422 date filter mismatch",
            params_shape=["date_from", "date_to"],
        )

    async with session_factory() as session:
        issue = (await session.execute(select(KnownIssue))).scalar_one()
    assert issue.report_count == 2, "F4: report_count must increment +1 per call (atomic UPDATE codepath)"
    assert issue.first_seen_at is not None
    assert issue.last_seen_at is not None


@pytest.mark.asyncio
async def test_f5_write_auto_feedback_event_increments_known_issue_via_sql_update(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
) -> None:
    """Two sequential auto-event matches must produce report_count=2 (atomic UPDATE codepath)."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "f5.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    feedback._auto_event_stamps.clear()
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        error_code="ToolError",
        error_excerpt="HTTP 500 date filter failed",
    )
    fingerprint = feedback.build_error_fingerprint_hash(incident)
    async with session_factory() as session:
        session.add(KnownIssue(
            status="open",
            category="bug",
            severity="medium",
            title="Open auto-event eligible",
            related_tool="get_payments",
            error_fingerprint_hash=fingerprint,
        ))
        await session.commit()

    await feedback.write_auto_feedback_event(
        credentials=credentials,
        tool_name="get_payments",
        exc=ToolError("HTTP 500 date filter failed"),
    )
    # Bypass dedup window for second invocation by manually deleting auto-report.
    async with session_factory() as session:
        for row in (await session.execute(select(AgentFeedbackReport))).scalars().all():
            await session.delete(row)
        await session.commit()

    await feedback.write_auto_feedback_event(
        credentials=credentials,
        tool_name="get_payments",
        exc=ToolError("HTTP 500 date filter failed"),
    )

    async with session_factory() as session:
        issue = (await session.execute(select(KnownIssue))).scalar_one()
    assert issue.report_count == 2, "F5: write_auto_feedback_event must use atomic UPDATE codepath"


@pytest.mark.skip(reason="F4/F5: true-concurrency test requires PostgreSQL fixture (not in default test suite)")
@pytest.mark.asyncio
async def test_f4_concurrent_create_feedback_report_no_lost_update_postgres_only() -> None:
    """Placeholder: when a Postgres test fixture is added, run two parallel create_feedback_report
    calls via asyncio.gather with separate sessions and assert report_count == 2 (not == 1).
    """
    raise NotImplementedError("Postgres fixture pending")


# ─── F13: collection-aware contains_any / contains_all ───────────────────────


def _rules_payload(op: str, expected_value):
    return json.dumps({
        "version": 1,
        "all": [
            {"field": "params_shape", "op": op, "value": expected_value},
        ],
    })


def _incident_with_params_shape(value):
    return feedback.FeedbackIncident(
        related_tool="get_payments",
        params_shape=value,
    )


def test_f13_contains_any_set_substring_no_false_positive() -> None:
    """params_shape={'foobar'}, contains_any:['foo'] — must be False (was True via str(set) repr)."""
    assert feedback.match_rules(
        _rules_payload("contains_any", ["foo"]),
        _incident_with_params_shape({"foobar"}),
    ) is False


def test_f13_contains_any_set_exact_member_true() -> None:
    assert feedback.match_rules(
        _rules_payload("contains_any", ["foo"]),
        _incident_with_params_shape({"foo", "bar"}),
    ) is True


def test_f13_contains_all_set_subset_true() -> None:
    assert feedback.match_rules(
        _rules_payload("contains_all", ["foo", "bar"]),
        _incident_with_params_shape({"foo", "bar", "baz"}),
    ) is True


def test_f13_contains_all_set_missing_member_false() -> None:
    assert feedback.match_rules(
        _rules_payload("contains_all", ["foo", "bar"]),
        _incident_with_params_shape({"foo"}),
    ) is False


def test_f13_contains_any_tuple_treated_as_collection() -> None:
    assert feedback.match_rules(
        _rules_payload("contains_any", ["foo"]),
        _incident_with_params_shape(("foo", "bar")),
    ) is True
    assert feedback.match_rules(
        _rules_payload("contains_any", ["nope"]),
        _incident_with_params_shape(("foo", "bar")),
    ) is False


def test_f13_contains_any_frozenset_treated_as_collection() -> None:
    assert feedback.match_rules(
        _rules_payload("contains_any", ["foo"]),
        _incident_with_params_shape(frozenset({"foo"})),
    ) is True


def test_f13_contains_any_str_legacy_substring_path_preserved() -> None:
    """For string fields (e.g., normalized_error_text), legacy substring semantics must remain."""
    rules = json.dumps({
        "version": 1,
        "all": [
            {"field": "normalized_error_text", "op": "contains_any", "value": ["date filter"]},
        ],
    })
    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        error_excerpt="HTTP 500 date filter failed",
    )
    assert feedback.match_rules(rules, incident) is True


# ─── F14: build_error_fingerprint_hash with http_status=0 ────────────────────


def test_f14_http_status_zero_produces_fingerprint(monkeypatch) -> None:
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage153-test-pepper")
    incident = feedback.FeedbackIncident(http_status=0)
    fingerprint = feedback.build_error_fingerprint_hash(incident)
    assert fingerprint is not None, "F14: http_status=0 must produce a fingerprint (was None via any())"
    assert fingerprint.startswith("hmac-sha256:")


def test_f14_empty_incident_still_returns_none(monkeypatch) -> None:
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage153-test-pepper")
    incident = feedback.FeedbackIncident()
    assert feedback.build_error_fingerprint_hash(incident) is None


# ─── F15: /readyz wraps storage check in asyncio.wait_for ─────────────────────


@pytest.mark.asyncio
async def test_f15_readyz_returns_503_on_storage_check_timeout(monkeypatch) -> None:
    """When check_storage_readiness hangs >timeout, /readyz must return 503 with reason=storage_check_timeout."""
    import web_routes_system

    async def hanging_readiness():
        await asyncio.sleep(5.0)
        return True, "ok"

    monkeypatch.setattr(web_routes_system, "check_storage_readiness", hanging_readiness)

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=10.0) as client:
        loop = asyncio.get_running_loop()
        start = loop.time()
        response = await client.get("/readyz")
        elapsed = loop.time() - start

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["checks"]["storage"]["status"] == "failed"
    assert payload["checks"]["storage"]["reason"] == "storage_check_timeout"
    assert elapsed < 4.0, f"F15: /readyz must return within ~timeout, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_f15_readyz_propagates_cancelled_error(monkeypatch) -> None:
    """asyncio.CancelledError raised inside check_storage_readiness must NOT become 503 — it propagates."""
    import web_routes_system

    async def cancelled_readiness():
        raise asyncio.CancelledError()

    monkeypatch.setattr(web_routes_system, "check_storage_readiness", cancelled_readiness)

    # Build app and call the registered route handler directly to observe propagation
    # rather than wrapping through ASGI which converts cancellations into 500s.
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    readyz_route = next(
        (route for route in app.routes if getattr(route, "path", None) == "/readyz"),
        None,
    )
    assert readyz_route is not None, "could not locate /readyz route on app"

    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/readyz",
        "raw_path": b"/readyz",
        "query_string": b"",
        "headers": [],
        "server": ("testserver", 80),
        "client": ("testclient", 12345),
        "scheme": "http",
        "root_path": "",
        "app": app,
    }

    async def _empty_receive():
        return {"type": "http.disconnect"}

    request = Request(scope, _empty_receive)
    with pytest.raises(asyncio.CancelledError):
        await readyz_route.endpoint(request)


# ─── F23: deploy-prod.yml deploy step has timeout-minutes ────────────────────


def test_f23_deploy_prod_yml_deploy_step_has_timeout_minutes() -> None:
    import yaml

    workflow_path = REPO_ROOT / ".github" / "workflows" / "deploy-prod.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))

    deploy_job = workflow["jobs"]["deploy"]
    steps = deploy_job["steps"]

    deploy_step = next(
        (s for s in steps if "deploy_server.sh" in (s.get("run") or "")),
        None,
    )
    assert deploy_step is not None, "F23: could not find step running deploy_server.sh"
    assert "timeout-minutes" in deploy_step, "F23: deploy_server.sh step must have timeout-minutes"
    assert isinstance(deploy_step["timeout-minutes"], int)
    assert 5 <= deploy_step["timeout-minutes"] <= 30, (
        f"F23: timeout-minutes should be 5..30 (got {deploy_step['timeout-minutes']})"
    )

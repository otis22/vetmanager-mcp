"""Stage 327 regression guards for message metrics and clinic-local dates."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import clinic_timezone
from runtime_auth import RuntimeCredentials, use_runtime_credentials
from service_metrics import reset_service_metrics, snapshot_service_metrics
from vetmanager_auth import VetmanagerAuthContext


@pytest.mark.asyncio
async def test_two_clinics_at_midnight_have_different_today_and_share_bounded_cache(monkeypatch):
    clinic_timezone.reset_clinic_timezone_cache()
    zones = {1: "Pacific/Auckland", 2: "America/Los_Angeles"}
    calls: list[str] = []

    class Client:
        async def get(self, path):
            calls.append(path)
            clinic_id = int(path.rsplit("/", 1)[1])
            return {"data": {"clinics": {"time_zone": zones[clinic_id]}}}

    monkeypatch.setattr(clinic_timezone, "VetmanagerClient", Client)
    instant = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    assert (await clinic_timezone.clinic_local_today(1, now=instant)).isoformat() == "2026-01-01"
    assert (await clinic_timezone.clinic_local_today(2, now=instant)).isoformat() == "2025-12-31"
    await clinic_timezone.clinic_local_today(1, now=instant)
    assert calls == ["/rest/api/clinics/1", "/rest/api/clinics/2"]


def test_message_tools_are_all_instrumented_ast_guard():
    """Break by replacing any call's instrument_call with direct post."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("tools/operations.py").read_text(encoding="utf-8"))
    expected = {"send_message_to_all", "send_message_to_users", "send_message_to_roles"}
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in expected:
            if any(isinstance(child, ast.Call) and getattr(child.func, "id", None) == "instrument_call" for child in ast.walk(node)):
                found.add(node.name)
    assert found == expected

"""Opt-in devtr6 probe using only records created for this test."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


pytestmark = pytest.mark.real_api


def _row(payload: dict, key: str) -> dict:
    rows = payload["data"][key]
    if isinstance(rows, list):
        assert len(rows) == 1
        return rows[0]
    return rows


def _synthetic_id(payload: dict, key: str, field: str, expected: str) -> int | None:
    rows = payload.get("data", {}).get(key, []) if isinstance(payload, dict) else []
    if isinstance(rows, dict):
        rows = [rows]
    matches = [row for row in rows if isinstance(row, dict) and row.get(field) == expected]
    return int(matches[0]["id"]) if len(matches) == 1 else None


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="Requires devtr6 TEST_DOMAIN/TEST_API_KEY")
async def test_stage475_live_synthetic_patient(capsys):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    marker = uuid.uuid4().hex[:12]
    client_id = pet_id = None
    observed = []
    original = httpx.AsyncClient.request

    async def capture(client, method, url, **kwargs):
        result = await original(client, method, url, **kwargs)
        path = str(url).split("/rest/api/", 1)[-1].split("/", 1)[0]
        if path in {"pet", "client", "clinics", "breed"}:
            observed.append((method, path, result.status_code))
        return result

    headers, runtime = patch_runtime_credentials(os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"])
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        try:
            clinics = (await mcp.call_tool("get_clinics", {"limit": 20})).structured_content
            clinic_rows = clinics["data"]["clinics"]
            clinic = next(row for row in clinic_rows if row.get("time_zone"))
            clinic_id = int(clinic["id"])
            breeds = (await mcp.call_tool("get_breeds", {"limit": 20})).structured_content
            breed = next(row for row in breeds["data"]["breed"] if row.get("pet_type_id"))
            client = (await mcp.call_tool("create_client", {
                "first_name": "Stage475", "last_name": f"Synthetic-{marker}"})).structured_content
            client_id = int(_row(client, "client")["id"])
            created = (await mcp.call_tool("create_pet", {
                "alias": f"Stage475-{marker}", "owner_id": client_id,
                "type_id": int(breed["pet_type_id"]), "breed_id": int(breed["id"]),
                "birthday": "2020-01-01"})).structured_content
            pet_id = int(_row(created, "pet")["id"])
            read = (await mcp.call_tool("get_pet_by_id", {"pet_id": pet_id})).structured_content
            row = _row(read, "pet")
            assert row["alias"] == f"Stage475-{marker}" and int(row.get("client_id", row.get("owner_id"))) == client_id
            assert row["status"] == "alive"

            with pytest.raises(Exception, match="change_pet_status"):
                await mcp.call_tool("update_pet", {"pet_id": pet_id, "status": "dead"})

            deathdate = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
            args = {"pet_id": pet_id, "expected_owner_id": client_id,
                    "clinic_id": clinic_id, "target_status": "dead", "deathdate": deathdate}
            preview = (await mcp.call_tool("change_pet_status", args)).structured_content
            assert preview["applied"] is False and preview["current_status"] == "alive"
            applied = (await mcp.call_tool("change_pet_status", {
                **args, "confirm": True, "confirmation": preview["confirmation"]})).structured_content
            assert applied["applied"] is True and applied["status"] == "dead"
            assert applied["deathdate"] == deathdate
            with capsys.disabled():
                print("STAGE475_LIVE", json.dumps({
                    "http_codes": observed, "old_tool_rejected": True,
                    "preview_body": {"applied": preview["applied"], "status": preview["current_status"]},
                    "confirm_body": {"applied": applied["applied"], "status": applied["status"],
                                     "deathdate": applied["deathdate"]}}, ensure_ascii=False))
        finally:
            cleanup_errors = []
            client_name = f"Synthetic-{marker}"
            pet_alias = f"Stage475-{marker}"
            created_client = any(method == "POST" and path == "client" and 200 <= code < 300
                                 for method, path, code in observed)
            created_pet = any(method == "POST" and path == "pet" and 200 <= code < 300
                              for method, path, code in observed)
            if client_id is None and created_client:
                try:
                    found = (await mcp.call_tool("get_clients", {"name": client_name, "limit": 20})).structured_content
                    client_id = _synthetic_id(found, "client", "last_name", client_name)
                except Exception:
                    pass
                if client_id is None:
                    cleanup_errors.append("created client could not be located for cleanup")
            if pet_id is None and created_pet:
                if client_id is not None:
                    try:
                        found = (await mcp.call_tool("get_pets", {
                            "owner_id": client_id, "alias": pet_alias, "limit": 20})).structured_content
                        pet_id = _synthetic_id(found, "pet", "alias", pet_alias)
                    except Exception:
                        pass
                if pet_id is None:
                    cleanup_errors.append("created pet could not be located for cleanup")
            if pet_id is not None:
                try:
                    deleted_pet = (await mcp.call_tool("delete_pet", {"pet_id": pet_id})).structured_content
                    if deleted_pet.get("success") is False:
                        cleanup_errors.append("pet cleanup rejected")
                except Exception:
                    cleanup_errors.append("pet cleanup failed")
            if client_id is not None:
                try:
                    deleted_client = (await mcp.call_tool("delete_client", {"client_id": client_id})).structured_content
                    if deleted_client.get("success") is False:
                        cleanup_errors.append("client cleanup rejected")
                except Exception:
                    cleanup_errors.append("client cleanup failed")
            assert not cleanup_errors, ", ".join(cleanup_errors)

"""Stage 475: sensitive status writes require a fresh, single-use preview."""

import json
from datetime import datetime, timezone

import httpx
import fakeredis
import pytest
import respx

import pet_status_confirmation
from clinic_timezone import reset_clinic_timezone_cache, resolve_clinic_timezone
from runtime_auth import use_runtime_credentials
from server import mcp
from tests.runtime_factories import make_runtime_credentials, patch_runtime_credentials
from tests.test_stage475_live import _synthetic_id
from vetmanager_client import VetmanagerClient, allow_pet_status_internal_read

BASE = "https://testclinic.vetmanager.cloud"
PET = {"id": 72, "owner_id": 41, "alias": "Test patient", "status": "alive",
       "deathdate": None, "edit_date": "2026-11-01 12:00:00", "birthday": "2020-01-01"}


def test_live_cleanup_lookup_requires_one_exact_synthetic_record():
    payload = {"data": {"client": [
        {"id": 71, "last_name": "Synthetic-other"},
        {"id": 72, "last_name": "Synthetic-marker"},
    ]}}
    assert _synthetic_id(payload, "client", "last_name", "Synthetic-marker") == 72
    assert _synthetic_id(payload, "client", "last_name", "Synthetic-missing") is None
    payload["data"]["client"].append({"id": 73, "last_name": "Synthetic-marker"})
    assert _synthetic_id(payload, "client", "last_name", "Synthetic-marker") is None


@pytest.mark.asyncio
async def test_published_update_pet_description_routes_status_to_confirmed_tool():
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    description = tools["update_pet"].to_mcp_tool().description
    assert "change_pet_status" in description
    assert "preview" in description and "confirmation" in description


def setup(state):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}}))
    respx.get(f"{BASE}/rest/api/clinics/1").mock(return_value=httpx.Response(
        200, json={"data": {"clinics": {"id": 1, "time_zone": "Europe/Moscow"}}}))
    respx.get(f"{BASE}/rest/api/clinics/2").mock(return_value=httpx.Response(
        200, json={"data": {"clinics": {"id": 2, "time_zone": "UTC"}}}))
    respx.get(f"{BASE}/rest/api/pet/72").mock(side_effect=lambda _: httpx.Response(
        200, json={"success": True, "data": {"pet": dict(state)}}))

    def write(request):
        data = json.loads(request.content)
        state.update(data)
        return httpx.Response(200, json={"success": True, "data": {"pet": dict(state)}})

    return respx.put(f"{BASE}/rest/api/pet/72").mock(side_effect=write)


async def call(name="change_pet_status", *, scopes=("pets.write",),
               is_depersonalized=False, **args):
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-secret", scopes=scopes, connection_id=7,
        bearer_token_id=3, is_depersonalized=is_depersonalized)
    with headers, runtime:
        result = await mcp.call_tool(name, args)
    return result.structured_content


@pytest.mark.asyncio
@respx.mock
async def test_preview_confirm_and_replay():
    state = dict(PET)
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    preview = await call(**args)
    assert preview["applied"] is False and put.call_count == 0
    assert preview["current_status"] == "alive"
    assert preview["clinic_id"] == 1 and "clinic" in preview["warning"]
    applied = await call(**args, confirm=True, confirmation=preview["confirmation"])
    assert applied["applied"] is True and put.call_count == 1
    assert state["status"] == "dead" and state["deathdate"].startswith("2026-11-01")
    with pytest.raises(Exception):
        await call(**args, confirm=True, confirmation=preview["confirmation"])
    assert put.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_devtr6_client_id_identifies_owner_and_conflict_is_rejected():
    state = dict(PET)
    state.pop("owner_id")
    state["client_id"] = 41
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    preview = await call(**args)
    assert preview["client_id"] == 41
    state["owner_id"] = 99
    with pytest.raises(Exception, match="owner"):
        await call(**args, confirm=True, confirmation=preview["confirmation"])
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_changed_owner_and_state_rejected_before_put():
    state = dict(PET)
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    preview = await call(**args)
    state["edit_date"] = "2026-11-02 12:00:00"
    with pytest.raises(Exception):
        await call(**args, confirm=True, confirmation=preview["confirmation"])
    state["owner_id"] = 99
    with pytest.raises(Exception):
        await call(**args)
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_alias_change_invalidates_preview_even_without_edit_date():
    state = dict(PET, edit_date=None)
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    preview = await call(**args)
    state["alias"] = "Another patient"
    with pytest.raises(Exception, match="changed"):
        await call(**args, confirm=True, confirmation=preview["confirmation"])
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_preview_alias_is_depersonalized():
    setup(dict(PET, alias="Иван Петров"))
    preview = await call(pet_id=72, expected_owner_id=41, clinic_id=1,
                         target_status="dead", deathdate="2026-11-01",
                         is_depersonalized=True)
    assert "Иван Петров" not in json.dumps(preview, ensure_ascii=False)


@pytest.mark.asyncio
@respx.mock
async def test_forbidden_dates_transitions_and_old_tool():
    state = dict(PET)
    put = setup(state)
    base = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead"}
    for bad in ("", "2026-02-30", "2099-01-01"):
        with pytest.raises(Exception):
            await call(**base, deathdate=bad)
    state["status"] = "deleted"
    with pytest.raises(Exception):
        await call(**base, deathdate="2026-11-01")
    with pytest.raises(Exception, match="change_pet_status"):
        await call("update_pet", pet_id=72, status="dead")
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_write_scope_only_and_readback_mismatch():
    state = dict(PET)
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    with pytest.raises(Exception):
        await call(scopes=("pets.read",), **args)
    with pytest.raises(Exception):
        await call("get_pet_by_id", pet_id=72)
    preview = await call(**args)
    def no_change(_):
        return httpx.Response(200, json={"success": True})
    put.mock(side_effect=no_change)
    result = await call(**args, confirm=True, confirmation=preview["confirmation"])
    assert result["applied"] is False and put.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_rest_read_exception_does_not_escape_tool_context():
    setup(dict(PET))
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-secret", scopes=("pets.write",))
    with headers, runtime:
        with pytest.raises(Exception, match="pets.read"):
            await VetmanagerClient().get("/rest/api/pet/72")
        with allow_pet_status_internal_read("/rest/api/pet/72"):
            with pytest.raises(Exception, match="pets.read"):
                await VetmanagerClient().get("/rest/api/pet/73")


@pytest.mark.asyncio
@respx.mock
async def test_dead_date_correction_writes_only_date():
    state = dict(PET, status="dead", deathdate="2026-10-01 00:00:00")
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    preview = await call(**args)
    applied = await call(**args, confirm=True, confirmation=preview["confirmation"])
    assert applied["applied"] is True
    assert json.loads(put.calls.last.request.content) == {"deathdate": "2026-11-01 00:00:00"}


@pytest.mark.asyncio
@respx.mock
async def test_token_bound_to_target_and_clinic():
    state = dict(PET)
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    preview = await call(**args)
    with pytest.raises(Exception):
        await call(**dict(args, deathdate="2026-11-02"), confirm=True,
                   confirmation=preview["confirmation"])
    with pytest.raises(Exception):
        await call(**args, confirm=True, confirmation=preview["confirmation"])
    preview = await call(**args)
    with pytest.raises(Exception):
        await call(**dict(args, clinic_id=2), confirm=True,
                   confirmation=preview["confirmation"])
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_missing_clinic_timezone_fails_before_put(monkeypatch):
    state = dict(PET)
    put = setup(state)
    async def unavailable(_, **kwargs):
        return None
    monkeypatch.setattr("tools.pet.resolve_clinic_timezone", unavailable)
    with pytest.raises(Exception, match="timezone"):
        await call(pet_id=72, expected_owner_id=41, clinic_id=1,
                   target_status="dead", deathdate="2026-11-01")
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_malformed_existing_birthday_fails_closed():
    state = dict(PET, birthday="20xx-01-01")
    put = setup(state)
    with pytest.raises(Exception, match="date could not be verified"):
        await call(pet_id=72, expected_owner_id=41, clinic_id=1,
                   target_status="dead", deathdate="2026-11-01")
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_malformed_date_suffix_fails_closed_before_and_after_put():
    state = dict(PET, birthday="2020-01-01 invalid")
    put = setup(state)
    args = {"pet_id": 72, "expected_owner_id": 41, "clinic_id": 1,
            "target_status": "dead", "deathdate": "2026-11-01"}
    with pytest.raises(Exception, match="date could not be verified"):
        await call(**args)
    assert put.call_count == 0
    state["birthday"] = "2020-01-01"
    preview = await call(**args)
    def malformed_readback(_):
        state["status"] = "dead"
        state["deathdate"] = "2026-11-01 invalid"
        return httpx.Response(200, json={"success": True})
    put.mock(side_effect=malformed_readback)
    result = await call(**args, confirm=True, confirmation=preview["confirmation"])
    assert result["applied"] is False and result["outcome"] == "unknown"


@pytest.mark.asyncio
@respx.mock
async def test_today_uses_clinic_zone_across_utc_midnight(monkeypatch):
    state = dict(PET)
    put = setup(state)
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 20, 22, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("tools.pet.datetime", FixedDateTime)
    preview = await call(pet_id=72, expected_owner_id=41, clinic_id=1,
                         target_status="dead", deathdate="2026-11-21")
    assert preview["target_deathdate"] == "2026-11-21" and put.call_count == 0


def test_confirmation_expires_and_is_consumed_once(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("MCP_WORKER_SLOTS", "1")
    moment = [100.0]
    monkeypatch.setattr(pet_status_confirmation.time, "monotonic", lambda: moment[0])
    with use_runtime_credentials(make_runtime_credentials("testclinic", "test-secret")):
        token = pet_status_confirmation.issue({"pet": 72})
        moment[0] = 701.0
        with pytest.raises(Exception, match="expired"):
            pet_status_confirmation.consume(token, {"pet": 72})
        token = pet_status_confirmation.issue({"pet": 72})
        pet_status_confirmation.consume(token, {"pet": 72})
        with pytest.raises(Exception, match="reused"):
            pet_status_confirmation.consume(token, {"pet": 72})


def test_confirmation_is_bound_to_connection_and_credential(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("MCP_WORKER_SLOTS", "1")
    with use_runtime_credentials(make_runtime_credentials(
        "testclinic", "first-secret", connection_id=1)):
        token = pet_status_confirmation.issue({"pet": 72})
        other_token = pet_status_confirmation.issue({"pet": 72})
    with use_runtime_credentials(make_runtime_credentials(
        "testclinic", "second-secret", connection_id=2)):
        with pytest.raises(Exception, match="changed"):
            pet_status_confirmation.consume(token, {"pet": 72})
    with use_runtime_credentials(make_runtime_credentials(
        "testclinic", "second-secret", connection_id=1)):
        with pytest.raises(Exception, match="changed"):
            pet_status_confirmation.consume(other_token, {"pet": 72})


def test_multiple_workers_without_redis_fail_closed(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    with use_runtime_credentials(make_runtime_credentials("testclinic", "test-secret")):
        with pytest.raises(Exception, match="Shared confirmation store"):
            pet_status_confirmation.issue({"pet": 72})


def test_redis_confirmation_is_atomic_and_single_use(monkeypatch):
    backend = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(pet_status_confirmation, "_redis", lambda: backend)
    with use_runtime_credentials(make_runtime_credentials("testclinic", "test-secret")):
        token = pet_status_confirmation.issue({"pet": 72})
        pet_status_confirmation.consume(token, {"pet": 72})
        with pytest.raises(Exception, match="reused"):
            pet_status_confirmation.consume(token, {"pet": 72})


@pytest.mark.asyncio
async def test_devtr6_legacy_clinic_zone_is_resolved():
    class Client:
        async def get(self, _):
            return {"data": {"clinics": {"id": 1, "time_zone": "Europe/Kiev"}}}
    reset_clinic_timezone_cache()
    with use_runtime_credentials(make_runtime_credentials("testclinic", "test-secret")):
        zone = await resolve_clinic_timezone(1, client_factory=Client)
    assert zone is not None and zone.key == "Europe/Kyiv"


@pytest.mark.asyncio
async def test_clinic_timezone_rejects_mismatched_record_id():
    class Client:
        async def get(self, _):
            return {"data": {"clinics": {"id": 99, "time_zone": "Europe/Moscow"}}}
    reset_clinic_timezone_cache()
    with use_runtime_credentials(make_runtime_credentials("testclinic", "test-secret")):
        zone = await resolve_clinic_timezone(1, client_factory=Client)
    assert zone is None


@pytest.mark.asyncio
async def test_strict_clinic_timezone_rejects_missing_record_id():
    class Client:
        async def get(self, _):
            return {"data": {"clinics": {"time_zone": "Europe/Moscow"}}}
    reset_clinic_timezone_cache()
    with use_runtime_credentials(make_runtime_credentials("testclinic", "test-secret")):
        zone = await resolve_clinic_timezone(1, client_factory=Client,
                                             require_record_id=True)
    assert zone is None

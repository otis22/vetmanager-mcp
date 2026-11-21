"""Offline behavioral guards for the stage361 real-only write/restore harness."""

import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from tests import test_stage361_live_phone_groups as live

pytestmark = pytest.mark.real_api


def _response(description, card_id=2, *, success=True):
    return {"success": success, "data": {"medicalCards": {
        "id": card_id, "description": description,
        "patient_id": 3, "doctor_id": 4, "clinic_id": 5,
    }}}


class FakeClient:
    def __init__(self, responses, statuses):
        self.responses = iter(responses)
        self.statuses = iter(statuses)
        self.calls = []
        self.last_response_status_code = None

    async def get(self, path, *, fresh):
        self.calls.append(("get", path, fresh))
        self.last_response_status_code = next(self.statuses)
        return next(self.responses)

    async def put(self, path, *, json):
        self.calls.append(("put", path, json["description"]))
        self.last_response_status_code = next(self.statuses)
        return next(self.responses)


def test_baseline_guard_requires_exact_synthetic_card_and_context() -> None:
    baseline = "synthetic baseline"
    digest = hashlib.sha256(baseline.encode()).hexdigest()
    context = {"patient_id": 3, "doctor_id": 4, "clinic_id": 5}
    context_digest = hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    live._guard_baseline(_response(baseline), 2, digest, context_digest)
    for response, card_id, expected in [
        (_response(baseline), 3, context_digest),
        (_response(baseline + " foreign"), 2, context_digest),
        (_response(baseline), 2, "wrong-context-sha"),
    ]:
        with pytest.raises(AssertionError):
            live._guard_baseline(response, card_id, digest, expected)


def test_http_and_json_are_checked_strictly(capsys) -> None:
    client = SimpleNamespace(last_response_status_code=201)
    live._checked_response("put", client, {"success": True}, 201)
    for status, success in [(None, True), (200, True), (201, 1), (201, "true"), (201, False)]:
        client.last_response_status_code = status
        with pytest.raises(AssertionError):
            live._checked_response("put", client, {"success": success}, 201)
    assert "http_success" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_poll_uses_fresh_independent_client_and_records_hash(capsys, monkeypatch) -> None:
    baseline, probe = "baseline", "baseline\nprobe"
    read = FakeClient([_response(baseline), _response(probe)], [200, 200])
    write = FakeClient([], [])
    monkeypatch.setattr(live.asyncio, "sleep", lambda _: _no_wait())
    snapshot = await live._poll_description(read, write, 2, hashlib.sha256(probe.encode()).hexdigest(),
                                            hashlib.sha256(baseline.encode()).hexdigest(), 60, "probe")
    assert snapshot["description"] == probe
    assert len(read.calls) == 2 and all(call[2] is True for call in read.calls)
    assert write.calls == []
    output = capsys.readouterr().out
    assert "description_sha256=" in output and "elapsed_ms=" in output
    assert probe not in output
    # The timeout context already bounded GET; a post-GET clock tick must not
    # turn the correct target hash into a false concurrent-change failure.
    start = live.time.monotonic()
    ticks = iter((start, start + 61, start + 62))
    monkeypatch.setattr(live, "time", SimpleNamespace(monotonic=lambda: next(ticks)))

    async def immediate_card(*_):
        return {"description": probe}

    monkeypatch.setattr(live, "_fresh_card", immediate_card)
    assert (await live._poll_description(read, write, 2, hashlib.sha256(probe.encode()).hexdigest(),
                                         hashlib.sha256(baseline.encode()).hexdigest(), 60,
                                         "probe"))["description"] == probe


async def _no_wait(*_):
    return None


@pytest.mark.asyncio
async def test_poll_deadline_interrupts_a_slow_fresh_get() -> None:
    class SlowClient:
        async def get(self, path, *, fresh):
            await asyncio.sleep(0.1)
            return _response("baseline")

    with pytest.raises(TimeoutError):
        await live._poll_description(SlowClient(), object(), 2, "probe-sha", "baseline-sha",
                                     0.01, "probe")


@pytest.mark.asyncio
async def test_restore_only_exact_probe_hash_and_confirms_baseline() -> None:
    baseline, probe = "baseline", "baseline\nprobe"
    payload = {"patient_id": 3, "doctor_id": 4, "clinic_id": 5}
    read = FakeClient([_response(probe), _response(probe), _response(baseline)], [200, 200, 200])
    write = FakeClient([{"success": True}], [201])
    original_sleep = live.asyncio.sleep
    live.asyncio.sleep = _no_wait
    try:
        await live._restore(read, write, 2, payload, baseline, hashlib.sha256(probe.encode()).hexdigest())
    finally:
        live.asyncio.sleep = original_sleep
    assert write.calls == [("put", "/rest/api/MedicalCards/2", baseline)]
    assert len(read.calls) == 3
    foreign = FakeClient([_response("foreign")], [200])
    blocked_write = FakeClient([], [])
    with pytest.raises(AssertionError):
        await live._restore(foreign, blocked_write, 2, payload, baseline,
                            hashlib.sha256(probe.encode()).hexdigest())
    assert blocked_write.calls == []
    changed_context = _response(probe)
    changed_context["data"]["medicalCards"]["doctor_id"] = 6
    blocked_context = FakeClient([changed_context], [200])
    with pytest.raises(AssertionError):
        await live._restore(blocked_context, blocked_write, 2, payload, baseline,
                            hashlib.sha256(probe.encode()).hexdigest())
    assert blocked_write.calls == []


def test_failed_checks_never_expose_raw_description_or_response(capsys) -> None:
    secret = "private patient secret 000 000 00 00"
    response = _response(secret, success=False)
    with pytest.raises(AssertionError) as baseline_error:
        live._guard_baseline(response, 2, "wrong-sha", "wrong-context")
    client = SimpleNamespace(last_response_status_code=201)
    with pytest.raises(AssertionError) as json_error:
        live._checked_response("put", client, response, 201)
    output = capsys.readouterr().out + str(baseline_error.value) + str(json_error.value)
    assert secret not in output and "private patient" not in output
    assert hashlib.sha256(secret.encode()).hexdigest() not in output
    assert f"description_length={len(secret)}" not in output
    with pytest.raises(AssertionError) as mcp_error:
        live._assert_mcp_ok(SimpleNamespace(is_error=True, structured_content=response))
    assert secret not in str(mcp_error.value)


@pytest.mark.asyncio
async def test_client_exception_discards_upstream_text() -> None:
    secret = "private patient secret 000 000 00 00"

    async def failed_call():
        raise ValueError(secret)

    with pytest.raises(AssertionError) as error:
        await live._safe_call("put", failed_call())
    assert secret not in str(error.value)
    assert error.value.__suppress_context__ is True

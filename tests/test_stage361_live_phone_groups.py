"""Live, reversible privacy probe on the dedicated API-key test contour."""

import asyncio
import hashlib
import json
import os
import time

import pytest

from server import mcp
from tests.runtime_factories import make_client_with_resolved_runtime, patch_runtime_credentials


TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")
_ENDPOINT = "/rest/api/MedicalCards"
_CARD_ID = 2  # Dedicated synthetic devtr6 card; never select an arbitrary record.
_BASELINE_SHA = "25ec919a7b7f95c3b6fa29ab0ab072d1dd6e50fefc62ec270d77ecc12e60b2fd"
_CONTEXT_SHA = "d64866e6183a4a7952ffa44dff9d64dbc00d16c62993aa5e414a6672058ca15c"
_REQUIRED = ("patient_id", "doctor_id", "clinic_id")
_PROBE = (
    "stage361: таблица диуреза\n"
    "Показатели: 120 100 80 60\n"
    "Единица: мл\n"
    "Примечание: тел. 000 000 00 00"
)


def _sha(description: str) -> str:
    return hashlib.sha256(description.encode("utf-8")).hexdigest()


def _card(response: object) -> dict:
    if not isinstance(response, dict):
        return {}
    data = response.get("data", {})
    card = data.get("medicalCards") if isinstance(data, dict) else None
    if isinstance(card, list):
        card = card[0] if card else None
    return card if isinstance(card, dict) else {}


def _context(card: dict) -> dict:
    return {key: card.get(key) for key in _REQUIRED}


def _context_sha(card: dict) -> str:
    return _sha(json.dumps(_context(card), sort_keys=True, separators=(",", ":")))


def _technical_summary(label: str, card_id: int, response: dict, *, status: int | None = None,
                       elapsed_ms: float | None = None) -> None:
    """Print only technical evidence: no upstream body or description."""
    card = _card(response)
    description = str(card.get("description") or "")
    success = isinstance(response, dict) and response.get("success") is True
    print(
        f"stage361_{label} id={card_id} status={status} json_success={success} "
        f"card_present={bool(card)} card_id_matches={str(card.get('id')) == str(card_id)} "
        f"description_length={len(description)} description_sha256={_sha(description)} "
        f"elapsed_ms={elapsed_ms} "
        f"probe_marker={_PROBE in description} "
        f"clinical_row={'Показатели: 120 100 80 60' in description} "
        f"phone_marker={'Примечание: тел. [redacted-phone]' in description}",
        flush=True,
    )


def _checked_response(label: str, client: object, response: dict, expected_status: int,
                      *, elapsed_ms: float | None = None) -> None:
    status = client.last_response_status_code
    _technical_summary(label, _CARD_ID, response, status=status, elapsed_ms=elapsed_ms)
    if type(status) is not int or status != expected_status:
        raise AssertionError(f"{label}: unexpected HTTP status")
    if not isinstance(response, dict) or response.get("success") is not True:
        raise AssertionError(f"{label}: JSON success is not true")


async def _safe_call(label: str, call: object) -> object:
    try:
        return await call
    except Exception as exc:
        raise AssertionError(f"{label}: client call failed ({type(exc).__name__})") from None


def _assert_mcp_ok(result: object) -> None:
    if result.is_error:
        raise AssertionError("MCP card read failed")


def _guard_baseline(response: dict, card_id: int, expected_sha: str, context_sha: str) -> dict:
    card = _card(response)
    if str(card.get("id")) != str(card_id):
        raise AssertionError("Synthetic card ID changed")
    if not isinstance(card.get("description"), str):
        raise AssertionError("Synthetic baseline description is missing")
    if _sha(card["description"]) != expected_sha:
        raise AssertionError("Synthetic baseline hash changed")
    if not all(card.get(key) for key in _REQUIRED):
        raise AssertionError("Synthetic update context incomplete")
    if _context_sha(card) != context_sha:
        raise AssertionError("Synthetic update context changed")
    return card


async def _fresh_card(client: object, card_id: int, label: str) -> dict:
    started = time.monotonic()
    response = await _safe_call(label, client.get(f"{_ENDPOINT}/{card_id}", fresh=True))
    elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    _checked_response(label, client, response, 200, elapsed_ms=elapsed_ms)
    card = _card(response)
    if str(card.get("id")) != str(card_id):
        raise AssertionError(f"{label}: card missing or ID changed")
    if not isinstance(card.get("description"), str):
        raise AssertionError(f"{label}: description missing")
    return card


async def _poll_description(read_client: object, write_client: object, card_id: int,
                            target_sha: str, prior_sha: str, timeout_seconds: float,
                            label: str) -> dict:
    assert read_client is not write_client, "Read-back must use an independent client"
    started = time.monotonic()
    deadline = started + timeout_seconds
    attempt = 0
    while True:
        attempt += 1
        async with asyncio.timeout_at(deadline):
            card = await _fresh_card(read_client, card_id, f"{label}_poll_{attempt}")
        digest = _sha(card["description"])
        print(f"stage361_{label}_poll_attempt={attempt} elapsed_ms={round((time.monotonic()-started)*1000, 1)} "
              f"description_sha256={digest}", flush=True)
        if digest == target_sha and time.monotonic() <= deadline:
            return card
        if digest != prior_sha:
            raise AssertionError("Unexpected description during read-back; preserving newer content")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"{label}: target hash not visible within 60 seconds")
        await asyncio.sleep(min(1.0, remaining))


async def _restore(read_client: object, write_client: object, card_id: int, payload: dict,
                   baseline: str, probe_sha: str) -> None:
    current = await _fresh_card(read_client, card_id, "before_restore")
    baseline_sha = _sha(baseline)
    current_sha = _sha(current["description"])
    if _context(current) != payload:
        raise AssertionError("Update context changed; preserving newer content")
    if current_sha == probe_sha:
        started = time.monotonic()
        response = await _safe_call("restore_put", write_client.put(
            f"{_ENDPOINT}/{card_id}", json={**payload, "description": baseline}))
        _checked_response("restore_put", write_client, response, 201,
                          elapsed_ms=round((time.monotonic()-started)*1000, 1))
    else:
        if current_sha != baseline_sha:
            raise AssertionError("Description changed concurrently; preserving newer content")
    restored = await _poll_description(read_client, write_client, card_id, baseline_sha,
                                       probe_sha, 60, "restore")
    if _context(restored) != payload:
        raise AssertionError("Baseline context not restored")


@pytest.mark.real_api
def test_summary_never_prints_upstream_description_or_response_data(capsys) -> None:
    private_text = "patient secret token stage361: таблица диуреза"
    _technical_summary("put", 7, {"success": True, "message": private_text, "data": {
        "medicalCards": {"id": 7, "description": private_text}}}, status=201)
    output = capsys.readouterr().out
    assert private_text not in output and "patient secret token" not in output
    assert "id=7 status=201 json_success=True" in output
    assert f"description_length={len(private_text)}" in output


@pytest.mark.real_api
def test_summary_handles_put_without_card_body(capsys) -> None:
    _technical_summary("put", 7, {"success": True, "data": {}}, status=201)
    assert "card_present=False" in capsys.readouterr().out


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(
    TEST_DOMAIN != "devtr6" or not TEST_API_KEY,
    reason="Stage 361 live write/restore runs only on the devtr6 API-key test contour",
)
async def test_live_medical_card_numeric_row_and_marked_phone() -> None:
    write_client = make_client_with_resolved_runtime(TEST_DOMAIN, TEST_API_KEY)
    read_client = make_client_with_resolved_runtime(TEST_DOMAIN, TEST_API_KEY)
    original_response = await _safe_call(
        "baseline", read_client.get(f"{_ENDPOINT}/{_CARD_ID}", fresh=True))
    _checked_response("baseline", read_client, original_response, 200)
    original = _guard_baseline(original_response, _CARD_ID, _BASELINE_SHA, _CONTEXT_SHA)
    baseline = original["description"]
    payload = _context(original)
    probe = baseline + "\n" + _PROBE
    probe_sha = _sha(probe)
    try:
        started = time.monotonic()
        response = await _safe_call("put", write_client.put(
            f"{_ENDPOINT}/{_CARD_ID}", json={**payload, "description": probe}))
        _checked_response("put", write_client, response, 201,
                          elapsed_ms=round((time.monotonic()-started)*1000, 1))
        # MCP runs before direct fresh read-back so this GET cannot prime its cache.
        headers_patch, runtime_patch = patch_runtime_credentials(
            TEST_DOMAIN, TEST_API_KEY, is_depersonalized=True,
        )
        with headers_patch, runtime_patch:
            result = await _safe_call("mcp_get", mcp.call_tool(
                "get_medical_card_by_id", {"card_id": _CARD_ID}))
        _technical_summary("mcp_get", _CARD_ID, result.structured_content or {})
        print(f"stage361_mcp_error={result.is_error}", flush=True)
        await _poll_description(read_client, write_client, _CARD_ID, probe_sha,
                                _BASELINE_SHA, 60, "probe")
        _assert_mcp_ok(result)
        cleaned = str(_card(result.structured_content).get("description") or "")
        if ("Показатели: 120 100 80 60\nЕдиница: мл" not in cleaned or
                "Примечание: тел. [redacted-phone]" not in cleaned or
                "000 000 00 00" in cleaned):
            raise AssertionError("MCP privacy or clinical-row contract failed")
        print("stage361_live_mcp_code=success", flush=True)
    finally:
        await _restore(read_client, write_client, _CARD_ID, payload, baseline, probe_sha)

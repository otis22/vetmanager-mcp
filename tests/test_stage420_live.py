"""Stage 420: live machine continuation on the .env Vetmanager test contour."""

import os
import re
import secrets
from uuid import uuid4

import httpx
import pytest

from tests.test_stage400_live import _call, _mcp_client
from tests.test_e2e_real import _post_with_csrf_sync

pytestmark = pytest.mark.real_api


def _register_live_account(web: httpx.Client) -> None:
    """Use a random password with guaranteed strength requirements."""
    email = f"stage420-{uuid4().hex}@example.test"
    response = _post_with_csrf_sync(web, "/register", data={
        "email": email, "password": f"Strong-Pass-123-{secrets.token_urlsafe(24)}"})
    assert response.status_code == 200, response.status_code
    response = _post_with_csrf_sync(web, "/account/integration", data={
        "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
        "api_key": os.environ["TEST_API_KEY"],
    }, page_path="/account")
    assert response.status_code == 200, response.status_code


def _issue_live_token(web: httpx.Client, *, depersonalized: bool) -> str:
    response = _post_with_csrf_sync(web, "/account/tokens", data={
        "token_name": "Stage 420 next-action proof", "expires_in_days": "1",
        "ip_mask": "*.*.*.*", "access_preset": "full_access",
        "confirm_full_access": "1", "is_depersonalized": "1" if depersonalized else "0",
    }, page_path="/account")
    assert response.status_code == 200, response.status_code
    token_match = re.search(r"vm_st_[A-Za-z0-9_-]+", response.text)
    assert token_match is not None
    return token_match.group(0)


def _seed_matched_report(client, *, year: int, request_id: int) -> tuple[int, str, int]:
    """Persist a report so the same data request can match it on a new job."""
    candidate_years = list(range(1980, year)) + list(range(year, year + 20))
    for candidate_year in candidate_years:
        intent = (
            f"Посчитай приёмы с 1 января {candidate_year} года по 31 декабря {candidate_year} года включительно. "
            "Результат — только две колонки: месяц приёма и количество приёмов в этом месяце. "
            "Группировка только по месяцу приёма; других фильтров и группировок нет. "
            "Без персональных данных."
        )
        _, response = _call(client, "create_report_ai_job", {
            "intent_text": intent, "wait_seconds": 30}, request_id)
        assert response.get("isError") is not True
        job = response["structuredContent"]["data"]["job"]
        seed_job_id = int(job["id"])
        request_id += 1
        for _ in range(12):
            if job["status"] in {"ready_to_save", "saved", "existing_report_matched", "failed", "rejected"}:
                break
            if job["status"] == "needs_confirmation":
                _, rejected = _call(client, "reject_report_ai_job_candidate", {
                    "job_id": seed_job_id}, request_id)
                assert rejected.get("isError") is not True
                request_id += 1
            _, polled = _call(client, "get_report_ai_job", {
                "job_id": seed_job_id, "wait_seconds": 30}, request_id)
            assert polled.get("isError") is not True
            job = polled["structuredContent"]["data"]["job"]
            request_id += 1
        if job["status"] in {"existing_report_matched", "saved"}:
            continue
        assert job["status"] == "ready_to_save", (
            f"candidate seed status={job['status']} job_id={seed_job_id}")
        break
    else:
        pytest.fail(f"candidate seed exhausted years {candidate_years[0]}..{candidate_years[-1]}; "
                    f"last status={job['status']} job_id={seed_job_id}")
    _, saved = _call(client, "save_report_ai_job_as_report", {
        "job_id": seed_job_id, "title": f"MCP candidate fixture {seed_job_id}"}, request_id)
    assert saved.get("isError") is not True
    saved_data = saved["structuredContent"]["data"]
    report_id = int(saved_data["report_id"])
    assert report_id > 0
    assert saved_data["next_action"]["call"]["tool"] == "get_report_ai_job_data"
    print(f"CANDIDATE_SEED job_id={seed_job_id} report_id={report_id} year={candidate_year}")
    return report_id, intent, request_id + 1


def _check_repeated_intent_dedup(client, *, seed_report_id: int, seed_intent: str,
                                 request_id: int, label: str) -> None:
    """A repeated data request must lead to a readable match or live confirmation."""
    intent = seed_intent[:-1] + "!"
    code, response = _call(client, "create_report_ai_job", {
        "intent_text": intent, "wait_seconds": 30}, request_id)
    assert response.get("isError") is not True
    job = response["structuredContent"]["data"]["job"]
    job_id = int(job["id"])
    request_id += 1
    statuses = [job.get("status")]
    for _ in range(6):
        if job.get("status") in {"existing_report_matched", "needs_confirmation",
                                 "ready_to_save", "saved", "failed", "rejected"}:
            break
        code, response = _call(client, "get_report_ai_job", {
            "job_id": job_id, "wait_seconds": 30}, request_id)
        request_id += 1
        assert response.get("isError") is not True, (job_id, statuses, response)
        job = response["structuredContent"]["data"]["job"]
        statuses.append(job.get("status"))
    assert job.get("status") in {"existing_report_matched", "needs_confirmation"}, (
        f"dedup failed: job_id={job_id} seed_report_id={seed_report_id} statuses={statuses}")
    outcome = job["status"]
    if outcome == "needs_confirmation":
        candidates = job.get("candidates") or []
        assert candidates, f"missing candidates: job_id={job_id} statuses={statuses}"
        candidate_id = int(candidates[0]["report_id"])
        assert candidate_id > 0
        calls = job["next_action"]["calls"]
        assert any(call["tool"] == "confirm_report_ai_job_candidate"
                   and call["arguments"] == {"job_id": job_id, "report_id": candidate_id}
                   and call["required_args"] == ["job_id", "report_id"]
                   for call in calls), (job_id, statuses, calls)
        assert any(call["tool"] == "reject_report_ai_job_candidate"
                   and call["arguments"] == {"job_id": job_id}
                   and call["required_args"] == ["job_id"]
                   for call in calls), (job_id, statuses, calls)
        code, response = _call(client, "confirm_report_ai_job_candidate", {
            "job_id": job_id, "report_id": candidate_id}, request_id)
        request_id += 1
        assert response.get("isError") is not True, (job_id, statuses, response)
        result = response["structuredContent"]["data"]
        assert int(result["report_id"]) > 0, (job_id, statuses, result)
        action = result["next_action"]
    else:
        assert int(job["report_id"]) > 0, (job_id, statuses)
        action = job["next_action"]
    assert action["call"] == {
        "tool": "get_report_ai_job_data", "arguments": {"job_id": job_id}}, (
            job_id, statuses, action)
    assert action["required_args"] == ["job_id"], (job_id, statuses, action)
    print(f"{label}_DEDUP HTTP {code} body={{'job_id': {job_id}, 'status': {outcome!r}, "
          f"'statuses': {statuses!r}, 'confirmed': {outcome == 'needs_confirmation'}}}")
    code, response = _call(client, "get_report_ai_job_data", {"job_id": job_id}, request_id)
    assert response.get("isError") is not True, (job_id, statuses, response)
    data = response["structuredContent"]["data"]
    assert "rows" in data, (job_id, statuses, data)
    assert data["next_action"]["call"]["tool"] == "rate_report_ai_job"
    print(f"{label}_DATA HTTP {code} body={{'job_id': {job_id}, 'status': {outcome!r}, "
          f"'total': {data.get('total')!r}}}")


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env Vetmanager test contour required")
def test_stage420_live_create_poll_save_data_rate(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        _register_live_account(web)
        token = _issue_live_token(web, depersonalized=False)
    with _mcp_client(live_server_url, token) as client:
        intent = ("Количество приёмов по месяцам за последние три месяца, без персональных данных. "
                  f"Метка проверки {uuid4().hex[:8]} не является фильтром данных.")
        code, response = _call(client, "create_report_ai_job", {
            "intent_text": intent, "wait_seconds": 30}, 2)
        assert response.get("isError") is not True
        job = response["structuredContent"]["data"]["job"]
        job_id = int(job["id"])
        print(f"STAGE420_CREATE HTTP {code} body={{'success': True, 'status': {job['status']!r}, 'next_action': {job.get('next_action')!r}}}")
        request_id = 3
        for _ in range(12):
            status = job["status"]
            if status in {"ready_to_save", "saved", "existing_report_matched", "failed", "rejected"}:
                break
            if status == "needs_confirmation":
                _, rejected = _call(client, "reject_report_ai_job_candidate", {"job_id": job_id}, request_id)
                assert rejected.get("isError") is not True
                request_id += 1
            code, response = _call(client, "get_report_ai_job", {
                "job_id": job_id, "wait_seconds": 30}, request_id)
            request_id += 1
            assert response.get("isError") is not True
            job = response["structuredContent"]["data"]["job"]
            print(f"STAGE420_POLL HTTP {code} body={{'success': True, 'status': {job['status']!r}, 'next_action': {job.get('next_action')!r}}}")
        assert job["status"] in {"ready_to_save", "saved", "existing_report_matched"}, job["status"]
        if job["status"] == "ready_to_save":
            assert job["next_action"]["call"]["tool"] == "save_report_ai_job_as_report"
            code, response = _call(client, "save_report_ai_job_as_report", {
                "job_id": job_id, "title": f"MCP next action verification {job_id}"}, request_id)
            request_id += 1
            assert response.get("isError") is not True
            data = response["structuredContent"]["data"]
            assert data["next_action"]["call"]["tool"] == "get_report_ai_job_data"
            print(f"STAGE420_SAVE HTTP {code} body={{'success': True, 'report_id_present': {bool(data.get('report_id'))}, 'next_action': {data['next_action']!r}}}")
        code, response = _call(client, "get_report_ai_job", {"job_id": job_id}, request_id)
        request_id += 1
        assert response.get("isError") is not True
        job = response["structuredContent"]["data"]["job"]
        assert job["next_action"]["call"]["tool"] == "get_report_ai_job_data"
        print(f"STAGE420_SAVED_STATUS HTTP {code} body={{'success': True, 'status': {job['status']!r}, 'next_action': {job['next_action']!r}}}")
        code, response = _call(client, "get_report_ai_job_data", {"job_id": job_id}, request_id)
        request_id += 1
        assert response.get("isError") is not True
        data = response["structuredContent"]["data"]
        assert data["next_action"]["call"]["tool"] == "rate_report_ai_job"
        assert data["next_action"]["required_args"] == ["job_id", "score", "intent_text"]
        print(f"STAGE420_DATA HTTP {code} body={{'success': True, 'total': {data.get('total')!r}, 'limited': {data.get('limited')!r}, 'next_action': {data['next_action']!r}}}")
        code, response = _call(client, "rate_report_ai_job", {
            "job_id": job_id, "score": 8, "intent_text": intent}, request_id)
        assert response.get("isError") is not True
        assert response["structuredContent"]["score"] == 8
        print(f"STAGE420_RATE HTTP {code} body={{'ok': True, 'score': 8}}")


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env Vetmanager test contour required")
def test_stage420_live_dedup_repeated_intent(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        _register_live_account(web)
        token = _issue_live_token(web, depersonalized=True)
    with _mcp_client(live_server_url, token) as client:
        seed_report_id, seed_intent, request_id = _seed_matched_report(client, year=2003, request_id=2)
        _check_repeated_intent_dedup(client, seed_report_id=seed_report_id,
                                     seed_intent=seed_intent, request_id=request_id,
                                     label="STAGE420")

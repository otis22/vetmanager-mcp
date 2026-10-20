"""Opt-in Stage 422 real Vetmanager calls on the .env API-key contour."""

import os
import re
import secrets
from uuid import uuid4

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync
from tests.test_stage400_live import _call, _mcp_client

pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env test contour required")
def test_stage422_live_reject_and_partial_profile(live_server_url):
    """Real upstream calls through an actual depersonalized service bearer."""
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        email = f"stage422-{secrets.token_hex(8)}@example.test"
        response = _post_with_csrf_sync(web, "/register", data={
            "email": email, "password": secrets.token_urlsafe(24)})
        assert response.status_code == 200
        response = _post_with_csrf_sync(web, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert response.status_code == 200
        response = _post_with_csrf_sync(web, "/account/tokens", data={
            "token_name": "Stage 422 privacy proof", "expires_in_days": "1",
            "ip_mask": "*.*.*.*", "access_preset": "full_access",
            "confirm_full_access": "1", "is_depersonalized": "1",
        }, page_path="/account")
        assert response.status_code == 200
        token = re.search(r"vm_st_[A-Za-z0-9_-]+", response.text)
        assert token is not None
        doctor_response = _post_with_csrf_sync(web, "/account/tokens", data={
            "token_name": "Stage 422 partial profile proof", "expires_in_days": "1",
            "ip_mask": "*.*.*.*", "access_preset": "doctor", "is_depersonalized": "1",
        }, page_path="/account")
        assert doctor_response.status_code == 200
        doctor_token = re.search(r"vm_st_[A-Za-z0-9_-]+", doctor_response.text)
        assert doctor_token is not None

    with _mcp_client(live_server_url, doctor_token.group(0)) as client:
        code, profile = _call(client, "get_pet_profile", {"pet_id": 66}, 2)
        body = profile.get("structuredContent") or {}
        assert profile.get("isError") is not True
        assert body.get("partial") is True
        assert body.get("section_errors")
        for error in body["section_errors"].values():
            assert error["message"] == "Section request failed; see error_type and retryable."
        print(f"STAGE422_PROFILE HTTP {code} body={{'partial': True, 'error_types': "
              f"{[e['error_type'] for e in body['section_errors'].values()]!r}}}")

    with _mcp_client(live_server_url, token.group(0)) as client:
        intent = ("Количество приёмов по месяцам за последние три месяца, "
                  f"без персональных данных. Проверка {uuid4().hex[:8]}.")
        _, created = _call(client, "create_report_ai_job", {
            "intent_text": intent, "wait_seconds": 30,
        }, 3)
        assert created.get("isError") is not True
        job = created["structuredContent"]["data"]["job"]
        job_id = int(job["id"])
        request_id = 4
        for _ in range(6):
            if job.get("status") == "needs_confirmation":
                break
            if job.get("status") in {"ready_to_save", "saved", "failed", "rejected", "existing_report_matched"}:
                break
            _, polled = _call(client, "get_report_ai_job", {"job_id": job_id, "wait_seconds": 30}, request_id)
            request_id += 1
            assert polled.get("isError") is not True
            job = polled["structuredContent"]["data"]["job"]
        if job.get("status") == "needs_confirmation":
            code, rejected = _call(client, "reject_report_ai_job_candidate", {"job_id": job_id}, request_id)
            assert rejected.get("isError") is not True
            result_job = rejected["structuredContent"]["data"]["job"]
            print(f"STAGE422_REJECT HTTP {code} body={{'success': True, 'status': {result_job.get('status')!r}}}")
            return
        # A tenant without a candidate has no successful reject path to prove.
        # Mark that external state explicitly instead of counting a 404 as proof.
        pytest.skip(f"stand offered no candidate for live reject: {job.get('status')}")

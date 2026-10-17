"""Opt-in live proof of the stage 409 reminder lifecycle on the .env test contour."""

import os
from uuid import uuid4

import httpx
import pytest

from tests.test_stage400_live import _call, _issue_bearer, _mcp_client


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env Vetmanager test contour required")
def test_stage409_live_reminder_before_and_after_rating(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        token, _ = _issue_bearer(web, "reminder")
    with _mcp_client(live_server_url, token) as client:
        intent = (
            "Количество приёмов по месяцам за последние три месяца, без персональных данных. "
            f"Метка проверки {uuid4().hex[:8]} не является фильтром данных."
        )
        code, created = _call(client, "create_report_ai_job", {
            "intent_text": intent, "wait_seconds": 30,
        }, 2)
        assert created.get("isError") is not True
        job = created["structuredContent"]["data"]["job"]
        job_id = int(job["id"])
        status = job.get("status")
        request_id = 3
        for _ in range(12):
            if status in {"ready_to_save", "saved", "existing_report_matched", "failed", "rejected"}:
                break
            if status == "needs_confirmation":
                _, rejected = _call(client, "reject_report_ai_job_candidate", {"job_id": job_id}, request_id)
                assert rejected.get("isError") is not True
                request_id += 1
            _, polled = _call(client, "get_report_ai_job", {
                "job_id": job_id, "wait_seconds": 30}, request_id)
            assert polled.get("isError") is not True
            status = polled["structuredContent"]["data"]["job"].get("status")
            request_id += 1
        assert status in {"ready_to_save", "saved", "existing_report_matched"}, status
        if status == "ready_to_save":
            _, saved = _call(client, "save_report_ai_job_as_report", {
                "job_id": job_id, "title": f"MCP rating reminder verification {job_id}",
            }, request_id)
            assert saved.get("isError") is not True
            request_id += 1
        code, before_status = _call(client, "get_report_ai_job", {"job_id": job_id}, request_id)
        request_id += 1
        assert before_status.get("isError") is not True
        status_job = before_status["structuredContent"]["data"]["job"]
        assert status_job["status"] in {"saved", "existing_report_matched"}
        assert "mcp_rating_reminder" in status_job
        print(f"STAGE409_STATUS_BEFORE HTTP {code} job_id={job_id} status={status_job['status']} reminder={status_job['mcp_rating_reminder']!r}")

        code, before_data = _call(client, "get_report_ai_job_data", {"job_id": job_id}, request_id)
        request_id += 1
        assert before_data.get("isError") is not True
        data = before_data["structuredContent"]["data"]
        assert "mcp_rating_reminder" in data
        print(f"STAGE409_DATA_BEFORE HTTP {code} total={data.get('total')} reminder={data['mcp_rating_reminder']!r}")

        code, rated = _call(client, "rate_report_ai_job", {
            "job_id": job_id, "score": 8, "intent_text": intent,
        }, request_id)
        request_id += 1
        assert rated.get("isError") is not True
        assert rated["structuredContent"]["score"] == 8
        print(f"STAGE409_RATE HTTP {code} body={{'ok': {rated['structuredContent']['ok']}, 'job_id': {job_id}, 'score': 8}}")

        code, after_status = _call(client, "get_report_ai_job", {"job_id": job_id}, request_id)
        request_id += 1
        assert after_status.get("isError") is not True
        after_job = after_status["structuredContent"]["data"]["job"]
        assert "mcp_rating_reminder" not in after_job
        print(f"STAGE409_STATUS_AFTER HTTP {code} job_id={job_id} status={after_job['status']} reminder=absent")
        code, after_data = _call(client, "get_report_ai_job_data", {"job_id": job_id}, request_id)
        assert after_data.get("isError") is not True
        assert "mcp_rating_reminder" not in after_data["structuredContent"]["data"]
        print(f"STAGE409_DATA_AFTER HTTP {code} reminder=absent")

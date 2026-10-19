"""Stage 420: live machine continuation on the .env Vetmanager test contour."""

import os
from uuid import uuid4

import httpx
import pytest

from tests.test_stage400_live import _call, _issue_bearer, _mcp_client

pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env Vetmanager test contour required")
def test_stage420_live_create_poll_save_data_rate(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        token, _ = _issue_bearer(web, "next-action")
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
def test_stage420_live_confirm_matched_candidate(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        token, _ = _issue_bearer(web, "confirm-next-action")
    with _mcp_client(live_server_url, token) as client:
        intent = ("Количество приёмов по месяцам за последние три месяца, без персональных данных. "
                  f"Метка проверки {uuid4().hex[:8]} не является фильтром данных.")
        code, response = _call(client, "create_report_ai_job", {"intent_text": intent, "wait_seconds": 30}, 2)
        assert response.get("isError") is not True
        job = response["structuredContent"]["data"]["job"]
        job_id = int(job["id"])
        request_id = 3
        for _ in range(6):
            if job["status"] == "needs_confirmation":
                break
            if job["status"] in {"ready_to_save", "saved", "existing_report_matched", "failed", "rejected"}:
                pytest.skip(f"stand offered {job['status']} without candidate")
            _, response = _call(client, "get_report_ai_job", {"job_id": job_id, "wait_seconds": 30}, request_id)
            request_id += 1
            assert response.get("isError") is not True
            job = response["structuredContent"]["data"]["job"]
        if job["status"] != "needs_confirmation":
            pytest.skip(f"stand did not offer a candidate after bounded polls: {job['status']}")
        candidates = job.get("candidates") or []
        assert candidates
        candidate_id = int(candidates[0]["report_id"])
        assert any(call["arguments"].get("report_id") == candidate_id
                   and call["required_args"] == ["job_id", "report_id"]
                   for call in job["next_action"]["calls"])
        assert any(call["tool"] == "reject_report_ai_job_candidate"
                   and call["required_args"] == ["job_id"]
                   for call in job["next_action"]["calls"])
        print(f"STAGE420_CONFIRM_CHOICE HTTP {code} body={{'success': True, 'status': 'needs_confirmation', 'candidate_count': {len(candidates)}, 'next_action_type': {job['next_action']['type']!r}}}")
        code, response = _call(client, "confirm_report_ai_job_candidate", {
            "job_id": job_id, "report_id": candidate_id}, request_id)
        request_id += 1
        assert response.get("isError") is not True
        data = response["structuredContent"]["data"]
        assert data["next_action"]["call"]["tool"] == "get_report_ai_job_data"
        print(f"STAGE420_CONFIRM HTTP {code} body={{'success': True, 'report_id_present': {bool(data.get('report_id'))}, 'next_action': {data['next_action']!r}}}")
        code, response = _call(client, "get_report_ai_job", {"job_id": job_id}, request_id)
        request_id += 1
        assert response.get("isError") is not True
        job = response["structuredContent"]["data"]["job"]
        assert job["status"] == "existing_report_matched"
        print(f"STAGE420_MATCHED_STATUS HTTP {code} body={{'success': True, 'status': {job['status']!r}, 'next_action': {job['next_action']!r}}}")
        code, response = _call(client, "get_report_ai_job_data", {"job_id": job_id}, request_id)
        assert response.get("isError") is not True
        data = response["structuredContent"]["data"]
        assert "rows" in data
        print(f"STAGE420_MATCHED_DATA HTTP {code} body={{'success': True, 'total': {data.get('total')!r}, 'next_action_type': {data['next_action']['type']!r}}}")

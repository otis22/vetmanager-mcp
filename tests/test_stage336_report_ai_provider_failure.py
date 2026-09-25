"""Stage 336 guards for Report AI provider transport failures."""

import pytest

from tool_descriptions import compose_tool_description
from tools import report_ai


PILOT_ERRORS = (
    "DeepSeek CURL error: Connection timed out after 10000 milliseconds",
    "DeepSeek CURL error: Connection timed out after 10001 milliseconds",
)


def _job(message: str, *, status: str = "failed", code: str = "PREVIEW_FAILED") -> dict:
    return {
        "status": status,
        "error_code": code,
        "error_message_safe": message,
    }


def _annotated_job(message: str, **overrides: str) -> dict:
    job = _job(message, **overrides)
    payload = {"success": True, "data": {"job": job}}
    report_ai._annotate_report_ai_workarounds(payload)
    return job


@pytest.mark.parametrize("message", PILOT_ERRORS)
def test_pilot_transport_failures_get_provider_workaround(message):
    workaround = _annotated_job(message)["mcp_workaround"]

    assert workaround["code"] == "report_ai_provider_unreachable"
    assert workaround["safe_to_retry"] is True
    guidance = " ".join(workaround["steps"] + workaround["do_not_do"]).lower()
    assert "do not rewrite" in guidance
    assert "do not create" in guidance
    assert "5 minutes" in guidance
    assert "one retry" in guidance
    assert "get_medical_cards_by_date" in guidance
    assert "get_admissions" in guidance
    assert "report_problem" in guidance
    assert "preview_failed" in guidance


@pytest.mark.parametrize("status", (408, 429, 500, 503, 599))
def test_transport_http_statuses_get_provider_workaround(status):
    job = _annotated_job(f"DeepSeek HTTP {status}: temporary provider failure")

    assert job["mcp_workaround"]["code"] == "report_ai_provider_unreachable"


@pytest.mark.parametrize("status", (400, 401, 403, 404, 499))
def test_non_transport_http_statuses_do_not_get_provider_workaround(status):
    job = _annotated_job(f"DeepSeek HTTP {status}: request rejected")

    assert "mcp_workaround" not in job


@pytest.mark.parametrize(
    ("message", "overrides"),
    (
        ("Renderer timeout", {}),
        ("Unrelated preview failure", {}),
        (PILOT_ERRORS[0], {"status": "recognizing"}),
        (PILOT_ERRORS[0], {"code": "INTENT_REJECTED"}),
    ),
)
def test_non_matching_failures_do_not_get_provider_workaround(message, overrides):
    workaround = _annotated_job(message, **overrides).get("mcp_workaround")
    assert not workaround or workaround["code"] != "report_ai_provider_unreachable"


def test_provider_workaround_wins_when_transport_and_good_id_markers_overlap():
    job = _annotated_job("DeepSeek CURL error: good.id connection timed out")

    assert job["mcp_workaround"]["code"] == "report_ai_provider_unreachable"


def test_get_report_ai_job_description_points_to_provider_workaround():
    description = compose_tool_description("get_report_ai_job") or ""

    assert "PREVIEW_FAILED" in description
    assert "provider" in description.lower()
    assert "job.mcp_workaround" in description

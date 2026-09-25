"""Stage 350 supersedes the pre-release Stage 296 renderer-cap assumption.

The observed 18.09 contract allows up to 10,000 rows and gives `limited=true`
when that response is truncated. At exactly 1,000 rows there is no longer a
basis for declaring probable truncation.
"""

from pathlib import Path

from tool_descriptions import compose_tool_description
from tools.report_ai import REPORT_AI_DATA_ROW_LIMIT, _annotate_report_ai_data_payload


def _payload(rows: int, *, limited: bool) -> dict:
    return {"data": {"rows": [{"id": i} for i in range(rows)], "total": rows,
                     "limited": limited, "csv_export_url": "/rest/api/report/StartReport?report_id=7"}}


def test_new_data_cap_and_flag_are_truthful():
    assert REPORT_AI_DATA_ROW_LIMIT == 10000
    guidance = _annotate_report_ai_data_payload(_payload(10000, limited=True))["data"]["mcp_large_result_guidance"]
    assert guidance["limited"] is True
    assert guidance["code"] == "report_ai_large_result"


def test_exactly_1000_rows_no_longer_trigger_truncation_claim():
    result = _annotate_report_ai_data_payload(_payload(1000, limited=False))
    assert "mcp_large_result_guidance" not in result["data"]


def test_descriptions_and_readme_match_release_contract():
    description = compose_tool_description("get_report_ai_job_data") or ""
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "10000 rows" in description
    assert "limited=true" in description
    assert "10 000 строк" in readme
    assert "структурно всегда `false`" not in readme
    for name in ("start_report_export", "get_report_ai_job_export"):
        assert "1000-row renderer cap" not in (compose_tool_description(name) or "")

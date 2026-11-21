"""Stage 480: exact catalog titles may bypass only the generic triple rule."""

import pytest
import httpx
import respx
import io
from unittest.mock import AsyncMock
from fastmcp.exceptions import ToolError

import depersonalization
import report_catalog_titles
import report_export
import tools as tools_module
import tools.report_ai as report_ai
from server import mcp
from tests.test_stage172_report_export_tools import BASE, CDN, billing_mock
from tests.runtime_factories import patch_runtime_credentials
from tests.export_shared import start_one_export

from depersonalization import REDACTED_NAME, REDACTED_PHONE, sanitize_report_cell, sanitize_tool_result


TITLE = "КОМПЛЕКТ СИНИЙ КРУГЛЫЙ"


def _json(value, titles):
    return sanitize_tool_result(
        {"data": {"columns": ["Наименование"], "rows": [{"Наименование": value}]}},
        report_mode=True, tool_name="get_report_ai_job_data", trusted_titles=titles,
    )["data"]["rows"][0]["Наименование"]


def test_catalog_title_and_csv_use_the_same_exact_value_rule():
    assert _json(TITLE, frozenset({TITLE})) == TITLE
    assert sanitize_report_cell("Наименование", TITLE, trusted_titles=frozenset({TITLE})) == TITLE
    for candidate in (f"{TITLE} добавка", f" {TITLE}"):
        assert _json(candidate, frozenset({TITLE})) != candidate
    assert _json(TITLE, frozenset({TITLE.title()})) == REDACTED_NAME
    assert _json(TITLE.title(), frozenset({TITLE})) == REDACTED_NAME
    assert _json(TITLE.title(), frozenset({TITLE.title()})) == REDACTED_NAME
    assert _json(TITLE, frozenset()) == REDACTED_NAME


def test_catalog_match_cannot_disable_other_pii_layers():
    cases = {
        "ИВАНОВ ПЁТР СЕРГЕЕВИЧ": REDACTED_NAME,
        "Иванов И. И.": REDACTED_NAME,
        "Пётр Сергеевич": REDACTED_NAME,
        "Иванов Пётр": REDACTED_NAME,
        "ИВАНОВ ПЁТР ПЛЮС": REDACTED_NAME,
        "ФИО ДЖОН СМИТ": REDACTED_NAME,
        "ФИО КАПРОВ ТИМОБ РЕЛОВ": REDACTED_NAME,
        "ФИО: КАПРОВ ТИМОБ РЕЛОВ": REDACTED_NAME,
        "ФИО:КАПРОВ ТИМОБ РЕЛОВ": REDACTED_NAME,
        "ФИО—КАПРОВ ТИМОБ РЕЛОВ": REDACTED_NAME,
        "ФИО·КАПРОВ ТИМОБ РЕЛОВ": REDACTED_NAME,
        "+7 (999) 123-45-67": REDACTED_PHONE,
        "user@example.com": "[redacted-email]",
        "ул. Ленина д. 5": "[redacted-address]",
    }
    for value, expected in cases.items():
        cleaned = _json(value, frozenset({value}))
        assert cleaned == expected
        assert sanitize_report_cell("Наименование", value, trusted_titles=frozenset({value})) == expected


def test_catalog_title_cannot_override_personal_column():
    assert sanitize_report_cell("ФИО", TITLE, trusted_titles=frozenset({TITLE})) == REDACTED_NAME
    assert sanitize_report_cell("Комментарий", TITLE, trusted_titles=frozenset({TITLE})) == REDACTED_NAME


def test_unknown_uppercase_name_is_owner_accepted_residual_risk():
    unknown = "КАПРОВ ТИМОБ РЕЛОВ"
    assert _json(unknown, frozenset({unknown})) == unknown


@pytest.mark.asyncio
async def test_catalog_snapshot_uses_only_five_titles_and_all_pages(monkeypatch):
    calls = []

    class Client:
        async def get(self, path, *, params, fresh, cache, retry):
            calls.append((path, params.copy(), fresh, cache, retry))
            name = path.removeprefix("/rest/api/")
            offset = params["offset"]
            total = 101 if name == "goodTag" else 1
            count = min(100, total - offset)
            return {"success": True, "data": {name: [
                {"title": TITLE, "description": "Иванов Пётр Сергеевич"}
                for _ in range(count)
            ], "totalCount": total}}

    monkeypatch.setattr(report_catalog_titles, "VetmanagerClient", Client)
    assert await report_catalog_titles.load_report_catalog_titles() == frozenset({TITLE})
    assert len(calls) == 6
    assert {path for path, _, _, _, _ in calls} == {
        f"/rest/api/{name}" for name in report_catalog_titles.CATALOGS
    }
    assert all(set(params) == {"limit", "offset"} and fresh and not cache and not retry
               for _, params, fresh, cache, retry in calls)


@pytest.mark.asyncio
async def test_incomplete_or_invalid_catalog_snapshot_fails_closed(monkeypatch):
    class Client:
        async def get(self, path, *, params, fresh, cache, retry):
            name = path.removeprefix("/rest/api/")
            return {"success": True, "data": {name: [{"title": TITLE}],
                    "totalCount": 2 if name == "goodTag" else 1}}

    monkeypatch.setattr(report_catalog_titles, "VetmanagerClient", Client)
    assert await report_catalog_titles.load_report_catalog_titles() == frozenset()


@pytest.mark.asyncio
async def test_catalog_snapshot_page_budget_fails_closed(monkeypatch):
    calls = 0

    class Client:
        async def get(self, path, *, params, fresh, cache, retry):
            nonlocal calls
            calls += 1
            return {"success": True, "data": {"good": [
                {"title": TITLE} for _ in range(100)
            ], "totalCount": 10200}}

    monkeypatch.setattr(report_catalog_titles, "VetmanagerClient", Client)
    assert await report_catalog_titles.load_report_catalog_titles() == frozenset()
    assert calls == report_catalog_titles.MAX_PAGES_PER_CATALOG


@pytest.mark.asyncio
@respx.mock
async def test_catalog_snapshot_calls_real_client_get_signature():
    billing_mock()
    for name in report_catalog_titles.CATALOGS:
        respx.get(f"{BASE}/rest/api/{name}").mock(return_value=httpx.Response(
            200, json={"success": True, "data": {
                name: [{"title": TITLE, "note": "Иванов Пётр Сергеевич"}],
                "totalCount": 1,
            }},
        ))
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime:
        titles = await report_catalog_titles.load_report_catalog_titles()
    assert titles == frozenset({TITLE})


@pytest.mark.asyncio
@respx.mock
async def test_catalog_snapshot_budget_counts_actual_http_attempts():
    billing_mock()
    first = respx.get(f"{BASE}/rest/api/good").mock(side_effect=[
        httpx.Response(503, json={"success": False, "message": "temporarily unavailable"}),
        httpx.Response(200, json={"success": True, "data": {
            "good": [{"title": TITLE}], "totalCount": 1,
        }}),
    ])
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime:
        assert await report_catalog_titles.load_report_catalog_titles() == frozenset()
    assert first.call_count == 1


def test_ai_proof_binds_file_clinic_and_access(monkeypatch):
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-480-synthetic-secret")
    report_export.reset_link_key_cache()
    proof = report_export.sign_ai_export_proof(
        report_file_id=17, domain="clinic-a", subject_type="bearer", subject_id=5,
    )
    valid = dict(report_file_id=17, domain="clinic-a", subject_type="bearer", subject_id=5)
    assert report_export.verify_ai_export_proof(proof, **valid)
    assert not report_export.verify_ai_export_proof(None, **valid)
    assert not report_export.verify_ai_export_proof(proof[:-1] + "ё", **valid)
    for changed in ({"report_file_id": 18}, {"domain": "clinic-b"}, {"subject_id": 6}):
        assert not report_export.verify_ai_export_proof(proof, **(valid | changed))


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("failure", [report_export.ReportExportError, RuntimeError])
async def test_missing_proof_key_does_not_turn_successful_export_start_into_error(monkeypatch, failure):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(
        200, json={"data": {"job": {"id": 22, "status": "saved", "report_id": 88}}},
    ))
    started = respx.get(f"{BASE}/rest/api/report/StartReport").mock(return_value=httpx.Response(
        200, json={"data": {"report": {"report_file_id": 123}}},
    ))
    monkeypatch.setattr(report_export, "sign_ai_export_proof", lambda **kw: (
        _ for _ in ()).throw(failure("no proof"))
    )
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime:
        result = (await mcp.call_tool("get_report_ai_job_export", {"job_id": 22})).structured_content
    assert result["data"]["report"]["report_file_id"] == 123
    assert "ai_export_proof" not in result["data"]["report"]
    assert started.call_count == 1


def test_name_guard_mutation_would_reveal_known_pair(monkeypatch):
    value = "Иванов Пётр"
    assert _json(value, frozenset({value})) == REDACTED_NAME
    monkeypatch.setattr(depersonalization, "redact_given_name_pairs", lambda text: text)
    assert _json(value, frozenset({value})) == value


@pytest.mark.asyncio
async def test_list_shaped_json_rows_are_rejected_before_catalog_exception(monkeypatch):
    monkeypatch.setattr(report_ai, "_call_vm", AsyncMock(return_value={
        "success": True,
        "data": {"columns": ["Комментарий"], "rows": [[TITLE]]},
    }))
    catalog = AsyncMock(return_value=frozenset({TITLE}))
    monkeypatch.setattr(tools_module, "load_report_catalog_titles", catalog)
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", is_depersonalized=True,
    )
    with headers, runtime, pytest.raises(ToolError, match="Report AI data is unavailable"):
        await mcp.call_tool("get_report_ai_job_data", {"job_id": 12})
    catalog.assert_not_awaited()


@pytest.mark.asyncio
@respx.mock
async def test_ai_export_proof_unmasks_csv_only_for_bound_file(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-480-synthetic-secret")
    monkeypatch.setenv("SITE_BASE_URL", "https://mcp.example")
    report_export.reset_link_key_cache()
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(
        200, json={"data": {"job": {"id": 22, "status": "saved", "report_id": 88}}},
    ))
    respx.get(f"{BASE}/rest/api/report/StartReport").mock(return_value=httpx.Response(
        200, json={"data": {"report": {"report_file_id": 123}}},
    ))
    respx.get(f"{BASE}/rest/api/report/reportFile").mock(return_value=httpx.Response(
        200, json={"success": True, "data": {"report": {"csv_file": CDN}}},
    ))
    monkeypatch.setattr(report_ai, "_download_export_bytes", AsyncMock(
        return_value=io.BytesIO(f"Наименование\n{TITLE}\n".encode()),
    ))
    monkeypatch.setattr(report_ai, "load_report_catalog_titles", AsyncMock(
        return_value=frozenset({TITLE}),
    ))
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token_id=1,
        is_depersonalized=True,
    )
    with headers, runtime:
        started = (await mcp.call_tool("get_report_ai_job_export", {"job_id": 22})).structured_content
        proof = started["data"]["report"]["ai_export_proof"]
        await mcp.call_tool("get_report_export_download", {"report_file_id": 123})
        await mcp.call_tool("get_report_export_download", {
            "report_file_id": 123, "ai_export_proof": proof,
        })
        await mcp.call_tool("get_report_export_download", {
            "report_file_id": 123, "ai_export_proof": proof[:-1] + "ё",
        })
    contents = [path.read_text(encoding="utf-8-sig") for path in tmp_path.rglob("*.csv")]
    assert sum(REDACTED_NAME in content for content in contents) == 2
    assert sum(TITLE in content for content in contents) == 1


@pytest.mark.asyncio
async def test_shared_real_export_start_uses_one_ai_job_when_selected():
    calls = []

    async def call_tool(name, arguments):
        calls.append((name, arguments))
        return type("Result", (), {"is_error": False, "structured_content": {
            "data": {"report": {"report_file_id": 123, "ai_export_proof": "proof"}},
        }})()

    outcome = await start_one_export(call_tool, 84, ai_job_id=2)
    assert calls == [("get_report_ai_job_export", {"job_id": 2})]
    assert outcome.require_file_id() == 123
    assert outcome.ai_export_proof == "proof"

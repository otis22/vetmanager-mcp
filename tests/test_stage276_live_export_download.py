"""Stage 276 — live proof that the export really goes through MCP.

A mock cannot show this one. The whole stage rests on what the Vetmanager
locator actually is, and on 01.09.2026 that turned out to be an unauthenticated
public CDN address. The group fixture starts one export during this node;
this test downloads it through the tool and reads the file back off the link the tool
returned.

    docker compose --env-file .env --profile test run --rm -T test \\
        python -m pytest -m real_api tests/test_stage276_live_export_download.py

Tenant guard refusal and an unfinished build are explicit failures in the
isolated export group; neither is counted as a passed or skipped node.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

import report_export
from server import mcp
from tests.runtime_factories import patch_runtime_credentials

pytest_plugins = ("tests.export_shared",)


TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not (TEST_DOMAIN and TEST_API_KEY),
    reason="TEST_DOMAIN and TEST_API_KEY are required for the live export test",
)


@pytest.fixture
def live_export_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "report-exports"
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(root))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-276-live-secret")
    monkeypatch.setenv("SITE_BASE_URL", "https://mcp.example")
    report_export.reset_link_key_cache()
    return root


@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_export_is_downloaded_cleaned_and_served_by_us(
    live_export_root: Path, shared_live_export
) -> None:
    headers_patch, runtime_patch = patch_runtime_credentials(
        TEST_DOMAIN, TEST_API_KEY, is_depersonalized=True
    )
    with headers_patch, runtime_patch:
        report_id = int(os.environ.get("REPORT_EXPORT_PROBE_REPORT_ID", "84"))
        ai_job_id = None
        if TEST_DOMAIN == "devtr6":
            assert report_id == 84, "The selected stand requires the approved AI export fixture."
            existing = await mcp.call_tool("get_report_ai_job", {"job_id": 2})
            job = existing.structured_content.get("data", {}).get("job", {})
            assert job.get("status") == "saved" and str(job.get("report_id")) == str(report_id), (
                "The approved AI export fixture is unavailable on the selected test stand."
            )
            ai_job_id = 2
        await shared_live_export.start_once(mcp.call_tool, report_id, ai_job_id=ai_job_id)
        report_file_id = shared_live_export.require_file_id()
        proof = shared_live_export.ai_export_proof()
        if ai_job_id is not None:
            assert isinstance(proof, str) and proof
            print("stage480 live get_report_ai_job_export code=success body=" + str({
                "report_file_id_present": report_file_id > 0,
                "ai_export_proof_present": bool(proof),
            }))
        payload = None
        for _ in range(12):
            try:
                result = await mcp.call_tool(
                    "get_report_export_download", {
                        "report_file_id": int(report_file_id),
                        **({"ai_export_proof": proof} if proof else {}),
                    }
                )
            except Exception as exc:  # build not ready yet is an ordinary state here
                if not any(marker in str(exc) for marker in (
                    "not ready", "FILE_BUILD_NOT_STARTED", "FILE_NOT_READY",
                )):
                    raise
                await asyncio.sleep(5)
                continue
            payload = result.structured_content
            break

    if payload is None:
        pytest.fail("Shared export build did not finish in the polling window")

    assert payload["download_url"].startswith("https://mcp.example/report-export/")
    assert "selcdn" not in str(payload)
    assert payload["depersonalized"] is True
    assert result.is_error is False
    print("stage450_live code=success body=" + str({
        "download_url": "https://mcp.example/report-export/<redacted>",
        "rows": payload["rows"], "columns": payload["columns"],
        "depersonalized": payload["depersonalized"],
        "ai_proof_used": bool(proof),
    }))

    stored = list(live_export_root.rglob("*.csv"))
    assert len(stored) == 1
    body = stored[0].read_text(encoding="utf-8-sig")
    assert body
    assert body.splitlines()[0]

    owner, name = payload["download_url"].rsplit("/", 2)[-2:]
    resolved = report_export.resolve_export(owner, name.removesuffix(".csv"))
    assert resolved is not None
    assert resolved.path == stored[0]
